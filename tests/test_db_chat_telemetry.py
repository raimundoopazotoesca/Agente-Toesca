from __future__ import annotations

from types import SimpleNamespace
from contextlib import nullcontext
import pytest

from tools import db_chat


def _response(**usage):
    return SimpleNamespace(usage=SimpleNamespace(**usage), choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


def test_attempts_preserve_usage_zero_unknown_fallback_and_context_reset(monkeypatch):
    calls = []
    responses = [RuntimeError("429 rate limit"), _response(prompt_tokens=0, completion_tokens=2,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=3), prompt_tokens_details=SimpleNamespace(cached_tokens=4))]
    providers = [{"name": "primary", "model": "m1", "api_key": "x", "base_url": "x"}, {"name": "fallback", "model": "m2", "api_key": "y", "base_url": "y"}]
    monkeypatch.setattr(db_chat, "_provider_chain", lambda: providers)
    class Client:
        def __init__(self, **_kwargs): pass
        @property
        def chat(self):
            def create(**_kwargs):
                value = responses.pop(0)
                calls.append(value)
                if isinstance(value, Exception): raise value
                return value
            return SimpleNamespace(completions=SimpleNamespace(create=create))
    monkeypatch.setattr(db_chat, "OpenAI", Client)
    attempts = []
    token = db_chat._TELEMETRY.set(attempts)
    try:
        response, provider = db_chat._chat_completion_with_fallback([{"role": "user", "content": "x"}])
    finally:
        db_chat._TELEMETRY.reset(token)
    assert response.choices[0].message.content == "ok"
    assert provider["model"] == "m2"
    assert [(a["provider"], a["model"], a["outcome"]) for a in attempts] == [("primary", "m1", "error"), ("fallback", "m2", "success")]
    assert attempts[1]["input_tokens"] == 0
    assert attempts[1]["output_tokens"] == 2
    assert attempts[1]["reasoning_tokens"] == 3
    assert attempts[1]["cached_tokens"] == 4
    assert db_chat._TELEMETRY.get() is None


def test_answer_no_llm_path_adds_honest_zero_usage():
    result = db_chat.answer("")
    assert result["answer_md"] == "Escribe una pregunta."
    assert result["usage"]["calls"] == 0
    assert result["usage"]["input_tokens"] is None


def test_answer_aggregates_complete_and_unknown_attempts_without_leak(monkeypatch):
    def fake_impl(_q, _h, _s):
        db_chat._record_attempt({"name": "a", "model": "m1"}, _response(prompt_tokens=100, completion_tokens=20, completion_tokens_details=SimpleNamespace(reasoning_tokens=1), prompt_tokens_details=SimpleNamespace(cached_tokens=2)), latency_ms=3)
        db_chat._record_attempt({"name": "b", "model": "m2"}, _response(prompt_tokens=50, completion_tokens=10, completion_tokens_details=SimpleNamespace(reasoning_tokens=2), prompt_tokens_details=SimpleNamespace(cached_tokens=3)), latency_ms=4)
        return {"answer_md": "same"}
    monkeypatch.setattr(db_chat, "_answer_impl", fake_impl)
    first = db_chat.answer("one")
    assert first["usage"]["calls"] == 2
    assert first["usage"]["input_tokens"] == 150
    assert first["usage"]["output_tokens"] == 30
    assert first["usage"]["reasoning_tokens"] == 3
    assert first["usage"]["cached_tokens"] == 5
    assert first["usage"]["llm_latency_ms"] == 7
    assert [a["model"] for a in first["usage"]["attempts"]] == ["m1", "m2"]
    def unknown_impl(_q, _h, _s):
        db_chat._record_attempt({"name": "a", "model": "m1"}, _response(prompt_tokens=100, completion_tokens=None, completion_tokens_details=SimpleNamespace(reasoning_tokens=None), prompt_tokens_details=SimpleNamespace(cached_tokens=None)), latency_ms=1)
        db_chat._record_attempt({"name": "b", "model": "m2"}, _response(prompt_tokens=None, completion_tokens=1, completion_tokens_details=SimpleNamespace(reasoning_tokens=1), prompt_tokens_details=SimpleNamespace(cached_tokens=1)), latency_ms=1)
        return {"answer_md": "same"}
    monkeypatch.setattr(db_chat, "_answer_impl", unknown_impl)
    second = db_chat.answer("two")
    assert second["usage"]["calls"] == 2
    assert all(second["usage"][field] is None for field in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens"))
    assert len(second["usage"]["attempts"]) == 2


def test_track_a_wall_clock_latency_is_independent_from_llm_latency(monkeypatch):
    from eval.benchmark.adapters.track_a_structured import _TrackASession
    class Sandbox:
        log = SimpleNamespace(reset=lambda: None, statements=[], violations=[])
    monkeypatch.setattr("eval.benchmark.adapters.track_a_structured.guarded_sqlite", lambda _sandbox: nullcontext())
    monkeypatch.setattr(db_chat, "answer", lambda *_a, **_k: {"answer_md": "ok", "usage": {"calls": 1, "input_tokens": 1, "output_tokens": 2, "reasoning_tokens": None, "cached_tokens": None, "llm_latency_ms": 7}})
    values = iter((10.0, 10.2))
    monkeypatch.setattr("eval.benchmark.adapters.track_a_structured.time.monotonic", lambda: next(values))
    turn = _TrackASession(Sandbox(), "s", []).ask("q")
    assert turn.usage.llm_latency_ms == 7
    assert turn.usage.latency_ms == pytest.approx(200)
