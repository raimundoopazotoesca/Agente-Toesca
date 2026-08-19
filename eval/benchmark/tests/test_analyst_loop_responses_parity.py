"""F4 Stage 2D: golden parity between `_OpenAIResponsesSession` (untouched)
and `AnalystLoop` driving `ResponsesTransport` + `LegacySqlActionExecutor`.

Special focus: opaque reasoning-item replay. A Responses-shaped script here
always includes a `reasoning` item alongside each `function_call` -- if the
transport's history rendering ever rebuilt `request_input` instead of
replaying `TranscriptItem.raw` verbatim, the reasoning item would be dropped
and this would be invisible in a text-only assertion, so the tests below
inspect the raw `input` payload of the *next* call, not just Turn.text.
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
from eval.benchmark.adapters.track_b_frontier import LegacySqlActionExecutor, _RUN_SQL_TOOL
from eval.benchmark.adapters.track_b_openai_responses import ResponsesTransport, _OpenAIResponsesSession
from eval.benchmark.snapshot import SnapshotSandbox

_RUN_SQL_SPEC = ToolSpec(name="run_sql", description=_RUN_SQL_TOOL["function"]["description"], parameters=_RUN_SQL_TOOL["function"]["parameters"])


@dataclass
class _ResponsesClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script[len(self.calls) - 1]


def _response(output, output_text=""):
    return SimpleNamespace(output=output, output_text=output_text,
                           usage=SimpleNamespace(input_tokens=None, output_tokens=None, input_tokens_details=None, output_tokens_details=None))


def _reasoning_and_call(call_id: str, query: str) -> list[dict]:
    """A round's output: an opaque reasoning item + a function_call. This
    shape is what a real Terra/Sol response looks like and what must survive
    replay verbatim."""
    return [
        {"type": "reasoning", "id": f"rs_{call_id}", "summary": []},
        {"type": "function_call", "call_id": call_id, "name": "run_sql", "arguments": json.dumps({"query": query})},
    ]


def _message(text: str) -> list[dict]:
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def _old_session(sandbox, client) -> _OpenAIResponsesSession:
    return _OpenAIResponsesSession(sandbox, "s", "sys", client, "gpt-5.6-terra")


def _new_loop(sandbox, client) -> AnalystLoop:
    transport = ResponsesTransport(client=client, model="gpt-5.6-terra", tool_specs=[_RUN_SQL_SPEC])
    executor = LegacySqlActionExecutor(sandbox=sandbox)
    return AnalystLoop(system_prompt="sys", transport=transport, action_executor=executor, tool_specs=[_RUN_SQL_SPEC])


# --- parity scenarios --------------------------------------------------------

def test_parity_direct_answer(sandbox):
    old = _old_session(sandbox, _ResponsesClient([_response(_message("respuesta directa"), "respuesta directa")]))
    old_turn = old.ask("pregunta")

    result = _new_loop(sandbox, _ResponsesClient([_response(_message("respuesta directa"), "respuesta directa")])).ask("pregunta")

    assert old_turn.text == result.turn.text == "respuesta directa"
    assert old_turn.usage.calls == result.turn.usage.calls == 1


def test_parity_tool_then_answer(sandbox):
    script_fn = lambda: [_response(_reasoning_and_call("c1", "SELECT 1 FROM dim_activo")), _response(_message("con datos"), "con datos")]
    old = _old_session(sandbox, _ResponsesClient(script_fn()))
    old_turn = old.ask("pregunta")

    result = _new_loop(sandbox, _ResponsesClient(script_fn())).ask("pregunta")

    assert old_turn.text == result.turn.text == "con datos"
    assert old_turn.usage.calls == result.turn.usage.calls == 2
    assert [tc.args["query"] for tc in old_turn.tool_calls] == [tc.args["query"] for tc in result.turn.tool_calls] == ["SELECT 1 FROM dim_activo"]


def test_parity_four_investigation_rounds_then_synthesis(sandbox):
    script_fn = lambda: [
        *[_response(_reasoning_and_call(str(i), f"SELECT {i} FROM dim_activo")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _response(_message("conclusion sintetizada"), "conclusion sintetizada"),
    ]
    old = _old_session(sandbox, _ResponsesClient(script_fn()))
    old_turn = old.ask("pregunta que agota el presupuesto")

    new_client = _ResponsesClient(script_fn())
    result = _new_loop(sandbox, new_client).ask("pregunta que agota el presupuesto")

    assert old_turn.text == result.turn.text == "conclusion sintetizada"
    assert old_turn.usage.calls == result.turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    assert new_client.calls[-1]["tool_choice"] == "none"
    for call in new_client.calls[:-1]:
        assert call["tool_choice"] == "auto"
    assert "no se alcanzo una respuesta final" not in result.turn.text


def test_parity_reasoning_items_replayed_verbatim_across_rounds(sandbox):
    """The critical Terra/Sol constraint. Checks the RAW input payload sent
    on round 2, not just Turn.text -- if replay silently dropped the round-1
    reasoning item, this is where it would show up as missing, not as any
    visible test failure on text alone."""
    script_fn = lambda: [
        _response(_reasoning_and_call("c1", "SELECT 1 FROM dim_activo")),
        _response(_message("fin"), "fin"),
    ]
    old_client = _ResponsesClient(script_fn())
    _old_session(sandbox, old_client).ask("pregunta")

    new_client = _ResponsesClient(script_fn())
    _new_loop(sandbox, new_client).ask("pregunta")

    old_round2_input = old_client.calls[1]["input"]
    new_round2_input = new_client.calls[1]["input"]

    old_reasoning = [i for i in old_round2_input if i.get("type") == "reasoning"]
    new_reasoning = [i for i in new_round2_input if i.get("type") == "reasoning"]
    assert old_reasoning == new_reasoning == [{"type": "reasoning", "id": "rs_c1", "summary": []}]

    old_fco = [i for i in old_round2_input if i.get("type") == "function_call_output"]
    new_fco = [i for i in new_round2_input if i.get("type") == "function_call_output"]
    assert [i["call_id"] for i in old_fco] == [i["call_id"] for i in new_fco] == ["c1"]


def test_parity_disobedient_provider_during_synthesis_is_ignored(sandbox):
    script_fn = lambda: [
        *[_response(_reasoning_and_call(str(i), f"SELECT {i} FROM dim_activo")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _response([*_message("conclusion final"), *_reasoning_and_call("rogue", "SELECT 999")], "conclusion final"),
    ]
    old_turn = _old_session(sandbox, _ResponsesClient(script_fn())).ask("pregunta")
    result = _new_loop(sandbox, _ResponsesClient(script_fn())).ask("pregunta")

    assert old_turn.text == result.turn.text == "conclusion final"
    assert len(old_turn.tool_calls) == len(result.turn.tool_calls) == MAX_INVESTIGATION_ROUNDS


def test_parity_provider_failure_propagates(sandbox):
    class _FailingClient:
        def __init__(self):
            self.responses = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError):
        _old_session(sandbox, _FailingClient()).ask("pregunta")
    with pytest.raises(RuntimeError):
        _new_loop(sandbox, _FailingClient()).ask("pregunta")
