"""F4 Stage 3: ActionRegistry / RunSqlAction.

Two things this file proves:
  1. Parity -- ActionRegistry(RunSqlAction) behaves identically to Stage 2's
     LegacySqlActionExecutor for every SQL scenario that mattered there.
  2. Extensibility -- the actual Stage 3 gate. Registering a second, non-SQL
     Action and having a scripted model call it requires zero changes to
     analyst_loop.py or any transport. Proven end-to-end through a real
     AnalystLoop + ChatCompletionsTransport, not just at the registry level.

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
from eval.benchmark.adapters.analyst_loop import AnalystLoop
from eval.benchmark.adapters.track_b_frontier import ChatCompletionsTransport, LegacySqlActionExecutor
from eval.benchmark.snapshot import SnapshotSandbox

_SENTINEL_SQL = "SELECT 1 FROM dim_activo"


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def _req(query: str, call_id: str = "1", name: str = "run_sql") -> ToolRequest:
    return ToolRequest(call_id=call_id, name=name, arguments={"query": query})


# =============================================================================
# Parity: ActionRegistry(RunSqlAction) vs LegacySqlActionExecutor
# =============================================================================

def test_parity_normal_query(sandbox):
    old = LegacySqlActionExecutor(sandbox=sandbox)
    new = ActionRegistry([RunSqlAction(sandbox=sandbox)])

    old_result = old.execute(_req(_SENTINEL_SQL))
    new_result = new.execute(_req(_SENTINEL_SQL))

    assert old_result.ok == new_result.ok is True
    assert old_result.content == new_result.content
    assert old_result.call_id == new_result.call_id == "1"


def test_parity_invalid_sql_empty(sandbox):
    old = LegacySqlActionExecutor(sandbox=sandbox)
    new = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    assert old.execute(_req("")).content == new.execute(_req("")).content
    assert old.execute(_req("")).ok == new.execute(_req("")).ok is False


def test_parity_write_attempt_rejected(sandbox):
    old = LegacySqlActionExecutor(sandbox=sandbox)
    new = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    q = "DELETE FROM dim_activo"
    old_result, new_result = old.execute(_req(q)), new.execute(_req(q))
    assert old_result.ok == new_result.ok is False
    assert old_result.content == new_result.content
    # never reached the sandbox -- caught by validate_sql before any connection


def test_parity_multi_statement_rejected(sandbox):
    old = LegacySqlActionExecutor(sandbox=sandbox)
    new = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    q = "SELECT 1; DROP TABLE dim_activo"
    assert old.execute(_req(q)).content == new.execute(_req(q)).content


def test_parity_result_truncation(sandbox):
    """Both inject an implicit LIMIT 50 into the SQL itself (before
    fetchmany(50) even runs), so the Python-side row cap is never actually
    exercised by any query issued through the tool -- `truncated` in the
    payload is always False in practice given that. What matters for parity
    is that both executors do the exact same thing, not that truncation
    fires."""
    old = LegacySqlActionExecutor(sandbox=sandbox)
    new = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    q = "SELECT * FROM raw_er_activo_line"
    old_result, new_result = old.execute(_req(q)), new.execute(_req(q))
    assert old_result.content == new_result.content
    payload = json.loads(new_result.content)
    assert len(payload["rows"]) <= 50
    assert payload["truncated"] is False


def test_parity_query_logging_and_gate_violations(sandbox):
    """Turn.queries/gate_violations come from the sandbox's own trace, not
    self-reported -- both executors must produce identical sandbox-side
    effects for the same query."""
    for executor in (LegacySqlActionExecutor(sandbox=sandbox), ActionRegistry([RunSqlAction(sandbox=sandbox)])):
        sandbox.log.reset()
        executor.execute(_req(_SENTINEL_SQL))
        assert any("dim_activo" in s.lower() for s in sandbox.log.statements)
        assert sandbox.log.violations == []


def test_parity_unknown_action_vs_unknown_tool_name():
    """Both must reject a name they don't recognize, explicitly, not crash."""
    sandbox_local = SnapshotSandbox()
    old = LegacySqlActionExecutor(sandbox=sandbox_local)
    new = ActionRegistry([RunSqlAction(sandbox=sandbox_local)])
    old_result = old.execute(_req("ignored", name="not_run_sql"))
    new_result = new.execute(_req("ignored", name="not_run_sql"))
    assert old_result.ok == new_result.ok is False
    assert "unknown" in json.loads(old_result.content)["error"].lower()
    assert "unknown" in json.loads(new_result.content)["error"].lower()


# =============================================================================
# Parity through the full loop: 4+1 synthesis and multi-turn, old vs new
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


def test_parity_four_investigation_rounds_then_synthesis_via_full_loop(sandbox):
    from eval.benchmark.adapters.analyst_loop import MAX_INVESTIGATION_ROUNDS, MAX_TOTAL_MODEL_ROUNDS

    script_fn = lambda: [
        *[_chat_response(None, [_tool_call(f"SELECT {i} FROM dim_activo", str(i))]) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _chat_response("conclusion sintetizada"),
    ]

    old_loop = AnalystLoop(
        system_prompt="sys",
        transport=ChatCompletionsTransport(client=_ChatClient(script_fn()), model="test-model", tool_specs=[_RUN_SQL_SPEC]),
        action_executor=LegacySqlActionExecutor(sandbox=sandbox), tool_specs=[_RUN_SQL_SPEC],
    )
    new_loop = AnalystLoop(
        system_prompt="sys",
        transport=ChatCompletionsTransport(client=_ChatClient(script_fn()), model="test-model", tool_specs=[_RUN_SQL_SPEC]),
        action_executor=ActionRegistry([RunSqlAction(sandbox=sandbox)]), tool_specs=[_RUN_SQL_SPEC],
    )

    old_result = old_loop.ask("pregunta que agota el presupuesto")
    new_result = new_loop.ask("pregunta que agota el presupuesto")

    assert old_result.turn.text == new_result.turn.text == "conclusion sintetizada"
    assert old_result.turn.usage.calls == new_result.turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    assert len(old_result.turn.tool_calls) == len(new_result.turn.tool_calls) == MAX_INVESTIGATION_ROUNDS


def test_parity_multiturn(sandbox):
    script = [
        _chat_response(None, [_tool_call("SELECT 1 FROM dim_activo")]), _chat_response("con datos t1"),
        _chat_response(None, [_tool_call("SELECT 2 FROM dim_activo")]), _chat_response("con datos t2"),
    ]
    old_loop = AnalystLoop(system_prompt="sys", transport=ChatCompletionsTransport(client=_ChatClient(list(script)), model="test-model", tool_specs=[_RUN_SQL_SPEC]),
                           action_executor=LegacySqlActionExecutor(sandbox=sandbox), tool_specs=[_RUN_SQL_SPEC])
    new_loop = AnalystLoop(system_prompt="sys", transport=ChatCompletionsTransport(client=_ChatClient(list(script)), model="test-model", tool_specs=[_RUN_SQL_SPEC]),
                           action_executor=ActionRegistry([RunSqlAction(sandbox=sandbox)]), tool_specs=[_RUN_SQL_SPEC])

    old_t1 = old_loop.ask("pregunta 1")
    old_t2 = old_loop.ask("pregunta 2", history=[
        TranscriptItem(role="user", text="pregunta 1"), TranscriptItem(role="assistant", text=old_t1.turn.text),
    ])
    new_t1 = new_loop.ask("pregunta 1")
    new_t2 = new_loop.ask("pregunta 2", history=[
        TranscriptItem(role="user", text="pregunta 1"), TranscriptItem(role="assistant", text=new_t1.turn.text),
    ])

    assert old_t2.turn.text == new_t2.turn.text == "con datos t2"


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
    used completely unmodified from Stage 2/3's SQL-only shape."""
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
