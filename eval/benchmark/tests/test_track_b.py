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

    def __post_init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        self.calls.append(messages)
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


def test_iteration_cap_produces_fallback_text(sandbox):
    """A model that keeps calling tools forever is cut off, not left hanging."""
    tool_call = _FakeToolCall(id="1", name="run_sql", arguments=json.dumps({"query": "SELECT 1"}))
    chat = _ScriptedClient(script=[_fake_response(None, [tool_call]) for _ in range(10)])
    session = _session(sandbox, chat)
    turn = session.ask("pregunta que nunca se resuelve")
    assert turn.usage.calls == 5  # MAX_TOOL_ITERATIONS
    assert "limite de iteraciones" in turn.text


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
    adapter = TrackBFrontier(sandbox=sandbox)
    assert adapter.name == "track_b_frontier"
    session = adapter.new_session("contract-check")
    assert hasattr(session, "ask")


def test_run_sql_tool_schema_shape():
    assert _RUN_SQL_TOOL["type"] == "function"
    assert _RUN_SQL_TOOL["function"]["name"] == "run_sql"
    assert "query" in _RUN_SQL_TOOL["function"]["parameters"]["properties"]
