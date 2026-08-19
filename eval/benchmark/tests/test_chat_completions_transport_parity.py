"""F4 Stage 2B: golden parity between the Stage 1 loop (`_TrackBSession`,
untouched) and the extracted `ChatCompletionsTransport`.

Both are driven from the identical scripted OpenAI-shaped client with the
identical script of responses. `_TrackBSession` runs its own real loop.
`ChatCompletionsTransport` is driven here by a minimal local harness
(`_drive`) that mirrors the same 4-investigation + 1-synthesis structure --
this is deliberately NOT AnalystLoop yet (that's Step 2C); it exists only to
prove the transport's wire-protocol translation is behaviorally identical to
what _TrackBSession does inline, before AnalystLoop is built on top of it.

No cutover here and no provider calls -- both sides use the same fake client.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.analyst_runtime.transport import ModelRequest, ToolRequest, ToolResult, ToolSpec, TranscriptItem
from eval.benchmark.adapters.track_b_frontier import (
    MAX_INVESTIGATION_ROUNDS,
    MAX_TOTAL_MODEL_ROUNDS,
    _RUN_SQL_TOOL,
    _SYNTHESIS_INSTRUCTION,
    ChatCompletionsTransport,
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


def _drive(sandbox, client, message: str) -> tuple[str, int, list[str]]:
    """Minimal stand-in for AnalystLoop, driving ChatCompletionsTransport
    through exactly the round structure Stage 1 defined. Executes run_sql the
    same way _TrackBSession._run_tool does, against the real sandbox, so
    Turn.queries parity is meaningful. Returns (final_text, model_calls,
    executed_sql)."""
    transport = ChatCompletionsTransport(client=client, model="test-model", tool_specs=[_RUN_SQL_SPEC])
    history: list[TranscriptItem] = []
    next_message = message
    executed_sql: list[str] = []
    final_text = ""

    for _ in range(MAX_INVESTIGATION_ROUNDS):
        response = transport.complete(ModelRequest(system_prompt="sys", history=history, message=next_message, tools=[_RUN_SQL_SPEC]))
        next_message = ""
        if not response.tool_requests:
            final_text = response.text
            history.append(TranscriptItem(role="user", text=message if not history else None))
            break
        results = []
        conn = sandbox.connect(guard=True)
        try:
            for tr in response.tool_requests:
                query = tr.arguments.get("query", "")
                executed_sql.append(query)
                try:
                    cur = conn.execute(query)
                    cur.fetchall()
                    results.append(ToolResult(call_id=tr.call_id, ok=True, content="{}"))
                except Exception as exc:
                    results.append(ToolResult(call_id=tr.call_id, ok=False, content=json.dumps({"error": str(exc)})))
        finally:
            conn.close()
        if not history:
            history.append(TranscriptItem(role="user", text=message))
        history.append(TranscriptItem(role="assistant", text=response.text, tool_requests=response.tool_requests, tool_results=results, raw=response.raw_items))
    else:
        response = transport.complete(ModelRequest(system_prompt="sys", history=history, message=_SYNTHESIS_INSTRUCTION, tools=[]))
        final_text = response.text

    return final_text, transport._round, executed_sql


# --- parity scenarios ----------------------------------------------------

def test_parity_direct_answer(sandbox):
    old = _old_session(sandbox, _ChatClient(script=[_chat_response("respuesta directa")]))
    old_turn = old.ask("hola")

    new_text, new_calls, _ = _drive(sandbox, _ChatClient(script=[_chat_response("respuesta directa")]), "hola")

    assert old_turn.text == new_text == "respuesta directa"
    assert old_turn.usage.calls == new_calls == 1


def test_parity_tool_then_answer(sandbox):
    script_fn = lambda: [_chat_response(None, [_tool_call("SELECT 1 FROM dim_activo")]), _chat_response("con datos")]
    old = _old_session(sandbox, _ChatClient(script=script_fn()))
    old_turn = old.ask("pregunta")

    new_text, new_calls, new_sql = _drive(sandbox, _ChatClient(script=script_fn()), "pregunta")

    assert old_turn.text == new_text == "con datos"
    assert old_turn.usage.calls == new_calls == 2
    assert [tc.args["query"] for tc in old_turn.tool_calls] == new_sql == ["SELECT 1 FROM dim_activo"]


def test_parity_multiple_tool_calls_same_round(sandbox):
    calls = [_tool_call("SELECT 1 FROM dim_activo", "1"), _tool_call("SELECT 2 FROM dim_activo", "2")]
    script_fn = lambda: [_chat_response(None, calls), _chat_response("listo")]
    old = _old_session(sandbox, _ChatClient(script=script_fn()))
    old_turn = old.ask("pregunta")

    new_text, new_calls, new_sql = _drive(sandbox, _ChatClient(script=script_fn()), "pregunta")

    assert old_turn.text == new_text
    assert len(old_turn.tool_calls) == len(new_sql) == 2


def test_parity_four_investigation_rounds_then_synthesis(sandbox):
    tool = lambda i: _tool_call(f"SELECT {i} FROM dim_activo", str(i))
    script_fn = lambda: [
        *[_chat_response(None, [tool(i)]) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _chat_response("conclusion sintetizada"),
    ]
    old = _old_session(sandbox, _ChatClient(script=script_fn()))
    old_turn = old.ask("pregunta que agota el presupuesto")

    new_text, new_calls, new_sql = _drive(sandbox, _ChatClient(script=script_fn()), "pregunta que agota el presupuesto")

    assert old_turn.text == new_text == "conclusion sintetizada"
    assert old_turn.usage.calls == new_calls == MAX_TOTAL_MODEL_ROUNDS
    assert len(new_sql) == MAX_INVESTIGATION_ROUNDS
    assert "no se alcanzo una respuesta final" not in new_text


def test_parity_synthesis_call_uses_tool_choice_none(sandbox):
    tool = lambda i: _tool_call(f"SELECT {i} FROM dim_activo", str(i))
    script = [*[_chat_response(None, [tool(i)]) for i in range(MAX_INVESTIGATION_ROUNDS)], _chat_response("fin")]

    old_client = _ChatClient(script=list(script))
    _old_session(sandbox, old_client).ask("pregunta")
    new_client = _ChatClient(script=list(script))
    _drive(sandbox, new_client, "pregunta")

    assert old_client.calls_kwargs[-1]["tool_choice"] == new_client.calls_kwargs[-1]["tool_choice"] == "none"
    for kwargs in old_client.calls_kwargs[:-1] + new_client.calls_kwargs[:-1]:
        assert kwargs["tool_choice"] == "auto"


def test_parity_max_five_model_calls(sandbox):
    tool = lambda i: _tool_call(f"SELECT {i} FROM dim_activo", str(i))
    script_fn = lambda: [*[_chat_response(None, [tool(i)]) for i in range(10)]]
    old = _old_session(sandbox, _ChatClient(script=script_fn() + [_chat_response("fin")] * 5))
    old_turn = old.ask("pregunta")
    new_text, new_calls, _ = _drive(sandbox, _ChatClient(script=script_fn() + [_chat_response("fin")] * 5), "pregunta")

    assert old_turn.usage.calls <= MAX_TOTAL_MODEL_ROUNDS
    assert new_calls <= MAX_TOTAL_MODEL_ROUNDS
