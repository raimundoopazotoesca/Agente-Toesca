"""Offline protocol tests for Round B's native OpenAI and Anthropic adapters."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.track_b_anthropic import TrackBAnthropic, _AnthropicSession
from eval.benchmark.adapters.track_b_frontier import (
    _RUN_SQL_TOOL,
    _TrackBSession,
    B1_STANDARD_PROFILES,
    resolve_b1_standard_profile,
)
from eval.benchmark.snapshot import SnapshotSandbox
from eval.round_b.incremental import IncrementalStore
from eval.round_b.runner import _effective_contract_hashes, live_adapter_factory
from eval.round_b.runner import RoundBRunner, build_run_manifest, validate_mini_dev


@dataclass
class _OpenAIToolCall:
    id: str
    name: str
    arguments: str

    @property
    def function(self):
        return SimpleNamespace(name=self.name, arguments=self.arguments)


def _openai_response(content, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or None))])


@dataclass
class _OpenAIClient:
    script: list
    calls: list[tuple[list[dict], dict]] = field(default_factory=list)

    def __post_init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.script[len(self.calls) - 1]


@dataclass
class _AnthropicClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script[len(self.calls) - 1]


def _anthropic_response(content, usage=None):
    return SimpleNamespace(content=content, usage=usage or SimpleNamespace(input_tokens=None, output_tokens=None))


def test_openai_models_have_frozen_native_profiles_and_no_overrides():
    for model in ("gpt-5.6-terra", "gpt-5.6-sol"):
        profile = resolve_b1_standard_profile("openai", model)
        assert profile.provider == "openai"
        assert profile.request_kwargs() == {}


def test_openai_request_uses_only_run_sql_and_default_parameters():
    sandbox = SnapshotSandbox()
    client = _OpenAIClient([_openai_response("respuesta")])
    session = _TrackBSession(sandbox, "s", "system", client, "gpt-5.6-terra", resolve_b1_standard_profile("openai", "gpt-5.6-terra"))
    session.ask("pregunta")
    _, kwargs = client.calls[0]
    assert kwargs["tools"] == [_RUN_SQL_TOOL]
    assert not ({"reasoning_effort", "temperature", "top_p", "seed"} & kwargs.keys())


def test_openai_replays_model_tool_result_model_loop():
    sandbox = SnapshotSandbox()
    tool = _OpenAIToolCall("tc_1", "run_sql", json.dumps({"query": "SELECT 1"}))
    client = _OpenAIClient([_openai_response(None, [tool]), _openai_response("final")])
    session = _TrackBSession(sandbox, "s", "system", client, "gpt-5.6-sol", resolve_b1_standard_profile("openai", "gpt-5.6-sol"))
    turn = session.ask("pregunta")
    assert turn.text == "final"
    assert turn.usage.calls == 2
    assert client.calls[1][0][-2]["tool_calls"][0]["function"]["name"] == "run_sql"
    assert client.calls[1][0][-1]["role"] == "tool"


def test_anthropic_models_have_frozen_native_profiles_and_adapter():
    for model in ("claude-sonnet-5", "claude-opus-5"):
        profile = resolve_b1_standard_profile("anthropic", model)
        assert profile.provider == "anthropic"
        assert profile.request_kwargs() == {}
    adapter = TrackBAnthropic(provider={"api_key": "offline", "model": "claude-sonnet-5"})
    assert adapter.name == "track_b_anthropic"


def test_anthropic_request_uses_only_run_sql_and_no_optional_overrides():
    sandbox = SnapshotSandbox()
    client = _AnthropicClient([_anthropic_response([{"type": "text", "text": "respuesta"}])])
    session = _AnthropicSession(sandbox, "s", "system", client, "claude-sonnet-5")
    session.ask("pregunta")
    request = client.calls[0]
    assert request["tools"] == [{"name": "run_sql", "description": _RUN_SQL_TOOL["function"]["description"], "input_schema": _RUN_SQL_TOOL["function"]["parameters"]}]
    assert not ({"temperature", "top_p", "top_k", "thinking", "budget_tokens"} & request.keys())


def test_anthropic_replays_private_thinking_in_memory_without_persisting_it(tmp_path):
    sandbox = SnapshotSandbox()
    private = "private-thought-never-persisted"
    assistant_blocks = [
        {"type": "thinking", "thinking": private, "signature": "opaque-signature"},
        {"type": "tool_use", "id": "toolu_1", "name": "run_sql", "input": {"query": "SELECT 1"}},
    ]
    client = _AnthropicClient([_anthropic_response(assistant_blocks), _anthropic_response([{"type": "text", "text": "final"}])])
    session = _AnthropicSession(sandbox, "s", "system", client, "claude-sonnet-5")
    turn = session.ask("pregunta")
    replayed_blocks = client.calls[1]["messages"][-2]["content"]
    assert replayed_blocks == assistant_blocks
    assert private not in repr(turn.raw)
    assert "opaque-signature" not in repr(turn.raw)

    store = IncrementalStore(tmp_path, "offline")
    store.turn({"final_answer": turn.text, "tool_calls": [x.__dict__ for x in turn.tool_calls], "executed_sql": turn.queries,
                "reasoning_tokens": 7, "provider_payload": {"thinking": private, "signature": "opaque-signature"}})
    store.event("provider_response_received", "anthropic", "case", 0, 0, 0,
                telemetry={"reasoning_tokens": 7, "redacted_thinking": private, "signature": "opaque-signature"})
    persisted = (store.turns_path.read_text(encoding="utf-8") + store.events_path.read_text(encoding="utf-8"))
    assert private not in persisted
    assert "opaque-signature" not in persisted
    assert "reasoning_tokens" in persisted


def test_anthropic_tce_history_keeps_only_final_visible_answer_after_a_turn():
    sandbox = SnapshotSandbox()
    private = "private-tce-thought"
    client = _AnthropicClient([
        _anthropic_response([{"type": "thinking", "thinking": private, "signature": "sig"},
                              {"type": "tool_use", "id": "toolu_1", "name": "run_sql", "input": {"query": "SELECT 1"}}]),
        _anthropic_response([{"type": "text", "text": "respuesta inicial"}]),
        _anthropic_response([{"type": "text", "text": "seguimiento"}]),
    ])
    session = _AnthropicSession(sandbox, "tce", "system", client, "claude-opus-5")
    session.ask("primera")
    session.ask("segunda")
    assert session.history == [{"role": "user", "content": "primera"}, {"role": "assistant", "content": "respuesta inicial"},
                               {"role": "user", "content": "segunda"}, {"role": "assistant", "content": "seguimiento"}]
    assert private not in repr(session.history)


def test_mini_dev_snapshot_and_runner_policy_are_frozen(tmp_path):
    mini = validate_mini_dev()
    manifest = build_run_manifest("offline", "0" * 40, "2026-08-18T00:00:00Z")
    assert (mini["canonical_manifest_sha256"], mini["case_count"], mini["turn_count"]) == (
        "df8cd68c690266e770210e752ab8078ef8f3dc23b175e55abe97963a18d3558f", 15, 25)
    assert manifest["snapshot"]["sha256"] == "592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c"
    assert manifest["max_model_tool_rounds"] == 5
    assert manifest["retry_policy"] == "one: 429/5xx/network/timeout"
    assert manifest["inference_profile"] == "B1_STANDARD"
    assert RoundBRunner(lambda *_: None, tmp_path).run_id


def test_native_provider_factory_routes_without_network(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline")
    assert live_adapter_factory("openai", "gpt-5.6-terra", resolve_b1_standard_profile("openai", "gpt-5.6-terra")).model == "gpt-5.6-terra"
    assert live_adapter_factory("anthropic", "claude-opus-5", resolve_b1_standard_profile("anthropic", "claude-opus-5")).model == "claude-opus-5"


def test_frozen_contract_hashes_and_profile_roster_are_unchanged():
    # system_prompt_sha256 re-pinned in a00d7ae's wake: commit a00d7ae
    # ("feat(analytics): add generic canonical semantic core") added
    # `aliases:` to semantic/entities.yaml, which _semantic_context() renders
    # verbatim into the system prompt. That is a legitimate, intentional
    # catalog change, not drift -- b155ded... was the pre-a00d7ae value;
    # b4c6dab... is the byte-verified post-a00d7ae value (schema_summary and
    # tool_schema_sha256 are unaffected).
    assert _effective_contract_hashes() == (
        "b4c6dab114ca78fbff88226cb02c380501fc5dfc9f13778e43bdf8d8b5e0c0b1",
        "d5623b5fc7f1cbc35d6f75b69403df87bbb326c9995d8e240f6a5e51d1b196ca",
    )
    assert {(p.provider, p.model) for p in B1_STANDARD_PROFILES} >= {
        ("openai", "gpt-5.6-terra"), ("openai", "gpt-5.6-sol"),
        ("anthropic", "claude-sonnet-5"), ("anthropic", "claude-opus-5"),
    }
