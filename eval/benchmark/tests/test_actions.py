"""F4 Stage 3: ActionRegistry / RunSqlAction.

Parity against LegacySqlActionExecutor was proven and recorded when this
class was introduced (commit "refactor(f4): introduce generic action
registry") -- every scenario below matched byte-for-byte before
LegacySqlActionExecutor was deleted. These tests now verify ActionRegistry(
RunSqlAction) directly, as the only implementation.

The main thing this file proves: Extensibility -- the actual Stage 3 gate.
Registering a second, non-SQL Action and having a scripted model call it
requires zero changes to analyst_loop.py or any transport. Proven end-to-end
through a real AnalystLoop + ChatCompletionsTransport, not just at the
registry level.

Offline only: real SQL against the real pinned snapshot through the real
sandbox (so gate F4 / QueryLog behavior is genuine), scripted LLM responses,
0 provider calls.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters._transport import ToolRequest, ToolResult, ToolSpec, TranscriptItem
from eval.benchmark.adapters.actions import Action, ActionRegistry, RunSqlAction
from eval.benchmark.adapters.analyst_loop import AnalystLoop, MAX_INVESTIGATION_ROUNDS, MAX_TOTAL_MODEL_ROUNDS
from eval.benchmark.adapters.track_b_frontier import ChatCompletionsTransport
from eval.benchmark.snapshot import SnapshotSandbox

_SENTINEL_SQL = "SELECT 1 FROM dim_activo"


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def _req(query: str, call_id: str = "1", name: str = "run_sql") -> ToolRequest:
    return ToolRequest(call_id=call_id, name=name, arguments={"query": query})


# =============================================================================
# RunSqlAction behavior (parity against LegacySqlActionExecutor already
# proven and on record; see module docstring)
# =============================================================================

def test_normal_query_succeeds(sandbox):
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    result = registry.execute(_req(_SENTINEL_SQL))
    assert result.ok is True
    assert result.call_id == "1"
    payload = json.loads(result.content)
    assert "columns" in payload and "rows" in payload


def test_empty_sql_rejected(sandbox):
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    result = registry.execute(_req(""))
    assert result.ok is False
    assert "vacia" in json.loads(result.content)["error"].lower()


def test_write_attempt_rejected(sandbox):
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    result = registry.execute(_req("DELETE FROM dim_activo"))
    assert result.ok is False
    # never reached the sandbox -- caught by validate_sql before any connection


def test_multi_statement_rejected(sandbox):
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    result = registry.execute(_req("SELECT 1; DROP TABLE dim_activo"))
    assert result.ok is False
    assert "una sentencia" in json.loads(result.content)["error"].lower()


def test_result_row_cap(sandbox):
    """LIMIT 50 is injected into the SQL itself (before fetchmany(50) even
    runs), so rows never exceed 50 and `truncated` is always False in
    practice -- this pins that real behavior, not an assumption."""
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    result = registry.execute(_req("SELECT * FROM raw_er_activo_line"))
    payload = json.loads(result.content)
    assert len(payload["rows"]) <= 50
    assert payload["truncated"] is False


def test_query_logging_and_gate_violations(sandbox):
    """Turn.queries/gate_violations come from the sandbox's own trace, not
    self-reported."""
    sandbox.log.reset()
    ActionRegistry([RunSqlAction(sandbox=sandbox)]).execute(_req(_SENTINEL_SQL))
    assert any("dim_activo" in s.lower() for s in sandbox.log.statements)
    assert sandbox.log.violations == []


# =============================================================================
# Through the full loop: 4+1 synthesis and multi-turn
# =============================================================================

@dataclass
class _FakeToolCall:
    id: str
    name: str
    arguments: str

    @property
    def function(self):
        return SimpleNamespace(name=self.name, arguments=self.arguments)


def _chat_response(content, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or None))])


@dataclass
class _ChatClient:
    script: list
    calls: list = field(default_factory=list)

    def __post_init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        self.calls.append(list(messages))
        return self.script[len(self.calls) - 1]


def _tool_call(query, call_id="1"):
    return _FakeToolCall(id=call_id, name="run_sql", arguments=json.dumps({"query": query}))


_RUN_SQL_SPEC = RunSqlAction(sandbox=None).tool_spec()


def test_four_investigation_rounds_then_synthesis_via_full_loop(sandbox):
    script = [
        *[_chat_response(None, [_tool_call(f"SELECT {i} FROM dim_activo", str(i))]) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _chat_response("conclusion sintetizada"),
    ]
    loop = AnalystLoop(
        system_prompt="sys",
        transport=ChatCompletionsTransport(client=_ChatClient(script), model="test-model", tool_specs=[_RUN_SQL_SPEC]),
        action_executor=ActionRegistry([RunSqlAction(sandbox=sandbox)]), tool_specs=[_RUN_SQL_SPEC],
    )
    result = loop.ask("pregunta que agota el presupuesto")

    assert result.turn.text == "conclusion sintetizada"
    assert result.turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    assert len(result.turn.tool_calls) == MAX_INVESTIGATION_ROUNDS
    assert "no se alcanzo una respuesta final" not in result.turn.text


def test_multiturn_via_full_loop(sandbox):
    script = [
        _chat_response(None, [_tool_call("SELECT 1 FROM dim_activo")]), _chat_response("con datos t1"),
        _chat_response(None, [_tool_call("SELECT 2 FROM dim_activo")]), _chat_response("con datos t2"),
    ]
    loop = AnalystLoop(system_prompt="sys", transport=ChatCompletionsTransport(client=_ChatClient(list(script)), model="test-model", tool_specs=[_RUN_SQL_SPEC]),
                       action_executor=ActionRegistry([RunSqlAction(sandbox=sandbox)]), tool_specs=[_RUN_SQL_SPEC])

    t1 = loop.ask("pregunta 1")
    t2 = loop.ask("pregunta 2", history=[
        TranscriptItem(role="user", text="pregunta 1"), TranscriptItem(role="assistant", text=t1.turn.text),
    ])

    assert t2.turn.text == "con datos t2"


# =============================================================================
# THE Stage 3 gate: a second, non-SQL action, with ZERO changes to
# analyst_loop.py or any transport.
# =============================================================================

@dataclass
class _EchoAction:
    """A fake, non-SQL action: no sandbox, no SnapshotSandbox, no SQL
    validation. Proves ActionRegistry dispatches on name alone, and that
    AnalystLoop never needs to know a new Action exists."""

    name: str = "echo_action"

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description="Echoes the given text back, uppercased.",
                        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})

    def execute(self, request: ToolRequest) -> ToolResult:
        text = request.arguments.get("text", "")
        return ToolResult(call_id=request.call_id, ok=True, content=json.dumps({"echoed": text.upper()}, ensure_ascii=False))


def test_second_nonsql_action_requires_no_analyst_loop_or_transport_change(sandbox):
    """register fake action -> scripted model calls it -> ActionRegistry
    dispatches -> AnalystLoop receives a ToolResult -> model answers.
    analyst_loop.py and track_b_frontier.py's ChatCompletionsTransport are
    used completely unmodified from their SQL-only shape."""
    echo = _EchoAction()
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox), echo])

    echo_call = _FakeToolCall(id="1", name="echo_action", arguments=json.dumps({"text": "hola"}))
    client = _ChatClient(script=[_chat_response(None, [echo_call]), _chat_response("el eco fue HOLA")])

    loop = AnalystLoop(
        system_prompt="sys",
        transport=ChatCompletionsTransport(client=client, model="test-model", tool_specs=registry.tool_specs()),
        action_executor=registry,
        tool_specs=registry.tool_specs(),
    )
    result = loop.ask("haz eco de 'hola'")

    assert result.turn.text == "el eco fue HOLA"
    assert result.turn.tool_calls[0].name == "echo_action"
    assert result.turn.tool_calls[0].ok is True
    # the tool result the model actually received
    sent_second_call = client.calls[1]
    tool_message = next(m for m in sent_second_call if m.get("role") == "tool")
    assert json.loads(tool_message["content"]) == {"echoed": "HOLA"}


def test_registry_exposes_tool_specs_for_all_registered_actions(sandbox):
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox), _EchoAction()])
    names = {spec.name for spec in registry.tool_specs()}
    assert names == {"run_sql", "echo_action"}


def test_registry_rejects_duplicate_action_names(sandbox):
    with pytest.raises(ValueError):
        ActionRegistry([RunSqlAction(sandbox=sandbox), RunSqlAction(sandbox=sandbox)])


def test_registry_unknown_action_returns_explicit_error_not_crash(sandbox):
    registry = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    result = registry.execute(_req("irrelevant", name="does_not_exist"))
    assert result.ok is False
    assert "unknown action" in json.loads(result.content)["error"]
    assert result.call_id == "1"
