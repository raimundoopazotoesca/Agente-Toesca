"""F4 Stage 2C: golden parity between the Stage 1 loop (`_TrackBSession`,
untouched) and the real `AnalystLoop` driving `ChatCompletionsTransport` +
`LegacySqlActionExecutor`.

This supersedes the temporary `_drive` harness from Step 2B's parity test --
that harness existed only to prove the transport's wire translation was
correct before AnalystLoop existed. Here the loop under test is the real
thing: no SQL import, no action-name comparison, no sandbox knowledge inside
AnalystLoop -- see test_analyst_loop_has_no_sql_knowledge below for the
architectural check that proves it structurally, not just by inspection.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters._transport import ToolSpec
from eval.benchmark.adapters.analyst_loop import AnalystLoop, MAX_INVESTIGATION_ROUNDS, MAX_TOTAL_MODEL_ROUNDS
from eval.benchmark.adapters.track_b_frontier import (
    ChatCompletionsTransport,
    LegacySqlActionExecutor,
    _RUN_SQL_TOOL,
    _TrackBSession,
)
from eval.benchmark.snapshot import SnapshotSandbox

_RUN_SQL_SPEC = ToolSpec(
    name=_RUN_SQL_TOOL["function"]["name"],
    description=_RUN_SQL_TOOL["function"]["description"],
    parameters=_RUN_SQL_TOOL["function"]["parameters"],
)


@dataclass
class _FakeToolCall:
    id: str
    name: str
    arguments: str

    @property
    def function(self):
        return SimpleNamespace(name=self.name, arguments=self.arguments)


def _chat_response(content: str | None, tool_calls: list[_FakeToolCall] | None = None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or None))])


@dataclass
class _ChatClient:
    script: list
    calls: list[list[dict]] = field(default_factory=list)
    calls_kwargs: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        self.calls.append(messages)
        self.calls_kwargs.append(kwargs)
        return self.script[len(self.calls) - 1]


def _tool_call(query: str, call_id: str = "1") -> _FakeToolCall:
    return _FakeToolCall(id=call_id, name="run_sql", arguments=json.dumps({"query": query}))


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def _old_session(sandbox, client) -> _TrackBSession:
    return _TrackBSession(sandbox=sandbox, session_id="parity", system_prompt="sys", client=client, model="test-model")


def _new_loop(sandbox, client) -> AnalystLoop:
    transport = ChatCompletionsTransport(client=client, model="test-model", tool_specs=[_RUN_SQL_SPEC])
    executor = LegacySqlActionExecutor(sandbox=sandbox)
    return AnalystLoop(system_prompt="sys", transport=transport, action_executor=executor, tool_specs=[_RUN_SQL_SPEC])


# --- parity scenarios ------------------------------------------------------

def test_parity_direct_answer_r1(sandbox):
    old = _old_session(sandbox, _ChatClient(script=[_chat_response("respuesta directa")]))
    old_turn = old.ask("hola")

    result = _new_loop(sandbox, _ChatClient(script=[_chat_response("respuesta directa")])).ask("hola")

    assert old_turn.text == result.turn.text == "respuesta directa"
    assert old_turn.usage.calls == result.turn.usage.calls == 1
    assert old_turn.tool_calls == result.turn.tool_calls == []


def test_parity_tool_then_answer(sandbox):
    script_fn = lambda: [_chat_response(None, [_tool_call("SELECT 1 FROM dim_activo")]), _chat_response("con datos")]
    old = _old_session(sandbox, _ChatClient(script=script_fn()))
    old_turn = old.ask("pregunta")

    result = _new_loop(sandbox, _ChatClient(script=script_fn())).ask("pregunta")

    assert old_turn.text == result.turn.text == "con datos"
    assert old_turn.usage.calls == result.turn.usage.calls == 2
    assert [tc.args["query"] for tc in old_turn.tool_calls] == [tc.args["query"] for tc in result.turn.tool_calls] == ["SELECT 1 FROM dim_activo"]


def test_parity_multiple_tool_calls_same_round(sandbox):
    calls = [_tool_call("SELECT 1 FROM dim_activo", "1"), _tool_call("SELECT 2 FROM dim_activo", "2")]
    script_fn = lambda: [_chat_response(None, calls), _chat_response("listo")]
    old = _old_session(sandbox, _ChatClient(script=script_fn()))
    old_turn = old.ask("pregunta")

    result = _new_loop(sandbox, _ChatClient(script=script_fn())).ask("pregunta")

    assert old_turn.text == result.turn.text
    assert len(old_turn.tool_calls) == len(result.turn.tool_calls) == 2


def test_parity_multiple_investigation_rounds(sandbox):
    script_fn = lambda: [
        _chat_response(None, [_tool_call("SELECT 1 FROM dim_activo", "1")]),
        _chat_response(None, [_tool_call("SELECT 2 FROM dim_activo", "2")]),
        _chat_response("conclusion tras 2 rondas"),
    ]
    old = _old_session(sandbox, _ChatClient(script=script_fn()))
    old_turn = old.ask("pregunta")

    result = _new_loop(sandbox, _ChatClient(script=script_fn())).ask("pregunta")

    assert old_turn.text == result.turn.text == "conclusion tras 2 rondas"
    assert old_turn.usage.calls == result.turn.usage.calls == 3


def test_parity_four_investigation_rounds_then_synthesis(sandbox):
    tool = lambda i: _tool_call(f"SELECT {i} FROM dim_activo", str(i))
    script_fn = lambda: [
        *[_chat_response(None, [tool(i)]) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _chat_response("conclusion sintetizada"),
    ]
    old = _old_session(sandbox, _ChatClient(script=script_fn()))
    old_turn = old.ask("pregunta que agota el presupuesto")

    new_client = _ChatClient(script=script_fn())
    result = _new_loop(sandbox, new_client).ask("pregunta que agota el presupuesto")

    assert old_turn.text == result.turn.text == "conclusion sintetizada"
    assert old_turn.usage.calls == result.turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    assert len(result.turn.tool_calls) == MAX_INVESTIGATION_ROUNDS
    assert "no se alcanzo una respuesta final" not in result.turn.text


def test_parity_synthesis_cannot_execute_tools(sandbox):
    """Even a disobedient provider that returns a tool call on the synthesis
    round must not have it executed -- AnalystLoop's synthesis branch never
    reads tool_requests back, structurally, not just via tool_choice."""
    tool = lambda i: _tool_call(f"SELECT {i} FROM dim_activo", str(i))
    script = [
        *[_chat_response(None, [tool(i)]) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _chat_response("conclusion final", [_FakeToolCall(id="99", name="run_sql", arguments=json.dumps({"query": "SELECT 999"}))]),
    ]
    old_client = _ChatClient(script=list(script))
    old_turn = _old_session(sandbox, old_client).ask("pregunta")

    new_client = _ChatClient(script=list(script))
    result = _new_loop(sandbox, new_client).ask("pregunta")

    assert old_turn.text == result.turn.text == "conclusion final"
    assert len(old_turn.tool_calls) == len(result.turn.tool_calls) == MAX_INVESTIGATION_ROUNDS  # the 5th tool call is ignored
    assert old_client.calls_kwargs[-1]["tool_choice"] == new_client.calls_kwargs[-1]["tool_choice"] == "none"


def test_parity_provider_failure_propagates(sandbox):
    class _FailingClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError):
        _old_session(sandbox, _FailingClient()).ask("pregunta")
    with pytest.raises(RuntimeError):
        _new_loop(sandbox, _FailingClient()).ask("pregunta")


def test_parity_never_exceeds_five_model_calls(sandbox):
    tool = lambda i: _tool_call(f"SELECT {i} FROM dim_activo", str(i))
    script_fn = lambda: [_chat_response(None, [tool(i)]) for i in range(10)] + [_chat_response("fin")] * 5
    old_turn = _old_session(sandbox, _ChatClient(script=script_fn())).ask("pregunta")
    result = _new_loop(sandbox, _ChatClient(script=script_fn())).ask("pregunta")

    assert old_turn.usage.calls <= MAX_TOTAL_MODEL_ROUNDS
    assert result.turn.usage.calls <= MAX_TOTAL_MODEL_ROUNDS


def test_parity_early_stopping_uses_fewer_than_five_calls(sandbox):
    old = _old_session(sandbox, _ChatClient(script=[_chat_response("directa, sin tools")]))
    old_turn = old.ask("hola")
    result = _new_loop(sandbox, _ChatClient(script=[_chat_response("directa, sin tools")])).ask("hola")

    assert old_turn.usage.calls == result.turn.usage.calls == 1 < MAX_TOTAL_MODEL_ROUNDS


# --- architectural checks (Stage 2, section 8) ------------------------------

def test_analyst_loop_has_no_sql_or_provider_knowledge():
    """Structural, not behavioral: inspects actual code constructs (imports,
    identifier references) via the AST, not a text/substring search --
    AnalystLoop's own docstring necessarily names "run_sql"/"openai"/etc. in
    prose to explain that none of them appear as real code, which a naive
    grep would wrongly flag."""
    import ast

    src = Path(__file__).resolve().parents[1] / "adapters" / "analyst_loop.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    imported_modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0] for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "openai" not in imported_modules
    assert "anthropic" not in imported_modules

    referenced_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced_names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for forbidden in ("SnapshotSandbox", "_validate_sql", "_run_tool", "run_sql"):
        assert forbidden not in referenced_names, f"AnalystLoop references {forbidden!r} as code, not just prose"

    # No comparison against the literal "run_sql" anywhere in real code (as
    # opposed to inside a docstring, which ast.Compare/ast.Constant-as-code
    # doesn't reach -- module/function docstrings are Expr statements, not
    # comparisons).
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Constant) and operand.value == "run_sql":
                    pytest.fail("AnalystLoop compares against the literal 'run_sql'")


def test_transport_has_no_reasoning_policy():
    """The inverse check: the transport must not know about round budgets or
    synthesis policy -- those live in analyst_loop.py, imported (re-exported)
    but never referenced by name inside ChatCompletionsTransport's own body."""
    src = Path(__file__).resolve().parents[1] / "adapters" / "track_b_frontier.py"
    text = src.read_text(encoding="utf-8")
    transport_body_start = text.index("class ChatCompletionsTransport")
    transport_body_end = text.index("def _safe_json_loads")
    body = text[transport_body_start:transport_body_end]
    forbidden = ["MAX_INVESTIGATION_ROUNDS", "MAX_TOTAL_MODEL_ROUNDS", "_SYNTHESIS_INSTRUCTION", "RESERVED_SYNTHESIS_ROUNDS"]
    for token in forbidden:
        assert token not in body, f"ChatCompletionsTransport leaked reasoning policy: {token!r}"
