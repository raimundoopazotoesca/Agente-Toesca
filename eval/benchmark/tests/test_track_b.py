"""Track B tests. No network/API calls -- the tool loop is exercised with a
scripted stand-in for the OpenAI client (same `.chat.completions.create()`
shape Track B calls for real) so these run offline and deterministically.
The actual SQL execution inside the loop is real, against the real pinned
snapshot, through the real sandbox -- only the LLM call is faked.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.track_b_frontier import (
    _RUN_SQL_TOOL,
    _TrackBSession,
    _schema_summary,
    _semantic_context,
    _validate_sql,
    TrackBFrontier,
)
from eval.benchmark.adapters.track_b_frontier import B1_STANDARD_PROFILES, InferenceProfile, resolve_b1_standard_profile
from eval.benchmark.snapshot import SnapshotSandbox


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


# --- pure helpers ------------------------------------------------------------

def test_validate_sql_accepts_select_and_with():
    assert _validate_sql("SELECT 1") is None
    assert _validate_sql("WITH t AS (SELECT 1) SELECT * FROM t") is None


@pytest.mark.parametrize(
    "sql",
    ["", "DELETE FROM dim_activo", "SELECT 1; DROP TABLE dim_activo", "PRAGMA writable_schema=1", "ATTACH ':memory:' AS x"],
)
def test_validate_sql_rejects_unsafe_or_malformed(sql):
    assert _validate_sql(sql) is not None


def test_schema_summary_excludes_bookkeeping_and_includes_business_tables(sandbox):
    summary = _schema_summary(sandbox)
    assert "dim_activo:" in summary
    assert "derived_kpi:" in summary
    assert "schema_version:" not in summary
    assert "sqlite_sequence:" not in summary


def test_semantic_context_includes_fondo_catalog():
    ctx = _semantic_context()
    assert "TRI" in ctx
    assert "vacancia_pct" in ctx  # from metrics/vacancia.yaml


# --- mock chat plumbing -------------------------------------------------------

@dataclass
class _FakeToolCall:
    id: str
    name: str
    arguments: str

    @property
    def function(self):
        return SimpleNamespace(name=self.name, arguments=self.arguments)


def _fake_response(content: str | None, tool_calls: list[_FakeToolCall] | None = None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@dataclass
class _ScriptedClient:
    """Stands in for the OpenAI client: replays a fixed sequence of
    responses, one per .chat.completions.create() call. A single pinned
    client/model is exactly Track B's real shape (see TrackBFrontier
    docstring on why providers aren't swapped mid-session)."""

    script: list
    calls: list[list[dict]] = field(default_factory=list)
    calls_kwargs: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        self.calls.append(messages)
        self.calls_kwargs.append(kwargs)
        idx = len(self.calls) - 1
        return self.script[idx]


_MODEL = "llama-3.3-70b-versatile"


def _session(sandbox, client) -> _TrackBSession:
    return _TrackBSession(
        sandbox=sandbox,
        session_id="test-session",
        system_prompt="system prompt for test",
        client=client,
        model=_MODEL,
    )


# --- tool loop ----------------------------------------------------------------

def test_single_tool_call_then_answer(sandbox):
    tool_call = _FakeToolCall(id="1", name="run_sql", arguments=json.dumps({"query": "SELECT COUNT(*) FROM dim_activo"}))
    chat = _ScriptedClient(script=[
        _fake_response(None, [tool_call]),
        _fake_response("Hay 17 activos."),
    ])
    session = _session(sandbox, chat)
    turn = session.ask("cuantos activos hay?")

    assert turn.text == "Hay 17 activos."
    assert turn.usage.calls == 2
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].ok is True
    assert turn.queries  # captured by the sandbox, not self-reported
    assert any("dim_activo" in q.lower() for q in turn.queries)
    assert not turn.gate_violations


def test_direct_answer_with_no_tool_call(sandbox):
    chat = _ScriptedClient(script=[_fake_response("No necesito consultar nada.")])
    session = _session(sandbox, chat)
    turn = session.ask("hola")
    assert turn.text == "No necesito consultar nada."
    assert turn.tool_calls == []
    assert turn.queries == []


def test_multiple_tool_calls_across_iterations(sandbox):
    tc1 = _FakeToolCall(id="1", name="run_sql", arguments=json.dumps({"query": "SELECT COUNT(*) FROM dim_activo WHERE fondo_key='PT'"}))
    tc2 = _FakeToolCall(id="2", name="run_sql", arguments=json.dumps({"query": "SELECT COUNT(*) FROM dim_activo WHERE fondo_key='Apo'"}))
    chat = _ScriptedClient(script=[
        _fake_response(None, [tc1]),
        _fake_response(None, [tc2]),
        _fake_response("PT tiene 3 activos, Apo tiene 2."),
    ])
    session = _session(sandbox, chat)
    turn = session.ask("compara cuantos activos tiene PT vs Apo")
    assert turn.usage.calls == 3
    assert len(turn.tool_calls) == 2
    assert len(turn.queries) == 2


def test_unsafe_tool_call_is_rejected_without_executing(sandbox):
    tool_call = _FakeToolCall(id="1", name="run_sql", arguments=json.dumps({"query": "DELETE FROM dim_activo"}))
    chat = _ScriptedClient(script=[
        _fake_response(None, [tool_call]),
        _fake_response("No pude borrar datos, esa operacion no esta permitida."),
    ])
    session = _session(sandbox, chat)
    turn = session.ask("borra la tabla de activos")
    assert turn.tool_calls[0].ok is False
    assert not turn.queries  # never reached the sandbox at all -- caught by _validate_sql
    assert not turn.gate_violations  # sandbox never even saw it


def test_iteration_cap_produces_synthesized_answer(sandbox):
    """A model that keeps calling tools forever is cut off and made to conclude.

    Pre-F4 this asserted the opposite -- that exhaustion produced the placeholder
    "(no se alcanzo una respuesta final...)". That was the defect, not the spec:
    it cost 17 of B27's 79 turns their entire answer. The budget is unchanged at
    5 model calls; the last one is now reserved for synthesis.
    """
    tool_call = _FakeToolCall(id="1", name="run_sql", arguments=json.dumps({"query": "SELECT 1"}))
    chat = _ScriptedClient(script=[
        *[_fake_response(None, [tool_call]) for _ in range(4)],
        _fake_response("Con la evidencia disponible, la conclusion es X."),
    ])
    session = _session(sandbox, chat)
    turn = session.ask("pregunta que nunca se resuelve")
    assert turn.usage.calls == 5  # 4 investigation + 1 reserved synthesis
    assert turn.text == "Con la evidencia disponible, la conclusion es X."
    assert "limite de iteraciones" not in turn.text


def test_history_persists_within_a_session(sandbox):
    chat = _ScriptedClient(script=[
        _fake_response("Primera respuesta."),
        _fake_response("Segunda respuesta."),
    ])
    session = _session(sandbox, chat)
    session.ask("primera pregunta")
    session.ask("segunda pregunta")
    # 2 turns * (user + assistant) = 4 messages in history
    assert len(session.history) == 4
    # second call's messages include the first turn's history
    second_call_messages = chat.calls[1]
    assert any(m.get("content") == "primera pregunta" for m in second_call_messages)


def test_two_sessions_do_not_share_history(sandbox):
    """Session isolation is inherent here -- there is no shared state module
    to leak across sessions in the first place."""
    chat_a = _ScriptedClient(script=[_fake_response("respuesta A")])
    chat_b = _ScriptedClient(script=[_fake_response("respuesta B")])
    session_a = _session(sandbox, chat_a)
    session_b = _session(sandbox, chat_b)
    session_a.ask("pregunta de sesion A")
    session_b.ask("pregunta de sesion B")
    assert session_a.history != session_b.history
    assert "pregunta de sesion A" not in str(session_b.history)


def test_track_b_satisfies_adapter_contract(sandbox):
    """Real construction (loads semantic context + schema summary against
    the real sandbox), no mocked chat needed for this check."""
    adapter = TrackBFrontier(
        sandbox=sandbox,
        provider={"api_key": "offline-test-key", "base_url": "https://example.invalid/v1", "model": _MODEL},
    )
    assert adapter.name == "track_b_frontier"
    session = adapter.new_session("contract-check")
    assert hasattr(session, "ask")


def test_run_sql_tool_schema_shape():
    assert _RUN_SQL_TOOL["type"] == "function"
    assert _RUN_SQL_TOOL["function"]["name"] == "run_sql"
    assert "query" in _RUN_SQL_TOOL["function"]["parameters"]["properties"]


def test_b1_standard_groq_explicitly_sends_medium_reasoning_without_sampling():
    profile = resolve_b1_standard_profile("groq", "openai/gpt-oss-120b")
    assert profile.request_kwargs() == {"reasoning_effort": "medium"}


def test_b1_standard_other_candidates_omit_all_sampling_and_reasoning_overrides():
    profile = resolve_b1_standard_profile("mistral", "mistral-large-2512")
    assert profile.request_kwargs() == {}
    assert len(B1_STANDARD_PROFILES) == 11


def test_b1_standard_fireworks_gpt_oss_uses_explicit_medium_reasoning():
    profile = resolve_b1_standard_profile("fireworks", "accounts/fireworks/models/gpt-oss-120b")
    assert profile.request_kwargs() == {"reasoning_effort": "medium"}


def test_fireworks_glm_omits_reasoning_override_and_replays_reasoning_in_memory(sandbox):
    profile = resolve_b1_standard_profile("fireworks", "accounts/fireworks/models/glm-5p2")
    assert profile.request_kwargs() == {}
    tc = _FakeToolCall(id="1", name="run_sql", arguments='{"query":"SELECT 1"}')
    first = _fake_response(None, [tc]); first.choices[0].message.reasoning_content = "private chain"
    chat = _ScriptedClient(script=[first, _fake_response("final")])
    session = _TrackBSession(sandbox, "s", "p", chat, "accounts/fireworks/models/glm-5p2", profile)
    turn = session.ask("q")
    assert chat.calls[1][-2]["reasoning_content"] == "private chain"
    assert "private chain" not in repr(turn.raw)


def test_session_passes_profile_kwargs_and_records_only_reported_usage(sandbox):
    response = _fake_response("respuesta")
    response.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, completion_tokens_details=SimpleNamespace(reasoning_tokens=3))
    chat = _ScriptedClient(script=[response])
    session = _TrackBSession(sandbox, "s", "p", chat, _MODEL, InferenceProfile("x", "m", "B1_STANDARD"))
    turn = session.ask("q")
    assert turn.usage.input_tokens == 11
    assert turn.usage.output_tokens == 7
    assert turn.usage.reasoning_tokens == 3
    assert turn.usage.cached_tokens is None
    assert "temperature" not in chat.calls_kwargs[0]


def test_each_model_round_emits_auditable_request_pair(sandbox):
    tc = _FakeToolCall(id="1", name="run_sql", arguments='{"query":"SELECT 1"}')
    chat = _ScriptedClient(script=[_fake_response(None, [tc]), _fake_response("final")])
    events = []
    session = _TrackBSession(sandbox, "s", "p", chat, _MODEL, None, request_observer=lambda kind, round, _: events.append((kind, round)))
    session.ask("q")
    assert events == [("provider_request_started", 0), ("provider_response_received", 0), ("provider_request_started", 1), ("provider_response_received", 1)]
