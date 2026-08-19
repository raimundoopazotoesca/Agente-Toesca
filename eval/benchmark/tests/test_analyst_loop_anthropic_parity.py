"""F4 Stage 2E/3: golden parity between `_AnthropicSession` (untouched) and
`AnalystLoop` driving `AnthropicTransport` + `ActionRegistry([RunSqlAction(...)])`.

Special focus: thinking/signature block replay and role alternation. Every
scripted tool-use response here carries a `thinking` block alongside
`tool_use`, and the tests inspect the RAW messages payload of the next call
(not just Turn.text) to prove those blocks -- and the required user/assistant
alternation -- survive replay exactly as Stage 1 required.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters._transport import ToolSpec
from eval.benchmark.adapters.actions import ActionRegistry, RunSqlAction
from eval.benchmark.adapters.analyst_loop import AnalystLoop, MAX_INVESTIGATION_ROUNDS, MAX_TOTAL_MODEL_ROUNDS
from eval.benchmark.adapters.track_b_anthropic import AnthropicTransport, _AnthropicSession
from eval.benchmark.adapters.track_b_frontier import _RUN_SQL_TOOL
from eval.benchmark.snapshot import SnapshotSandbox

_RUN_SQL_SPEC = ToolSpec(name="run_sql", description=_RUN_SQL_TOOL["function"]["description"], parameters=_RUN_SQL_TOOL["function"]["parameters"])


@dataclass
class _AnthropicClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script[len(self.calls) - 1]


def _reply(blocks):
    return SimpleNamespace(content=list(blocks), usage=SimpleNamespace(input_tokens=None, output_tokens=None))


def _thinking_and_tool_use(block_id: str, query: str) -> list[dict]:
    return [
        {"type": "thinking", "thinking": "razonando", "signature": f"sig_{block_id}"},
        {"type": "tool_use", "id": block_id, "name": "run_sql", "input": {"query": query}},
    ]


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def _old_session(sandbox, client) -> _AnthropicSession:
    return _AnthropicSession(sandbox, "s", "sys", client, "claude-sonnet-5")


def _new_loop(sandbox, client) -> AnalystLoop:
    transport = AnthropicTransport(client=client, model="claude-sonnet-5", tool_specs=[_RUN_SQL_SPEC])
    executor = ActionRegistry([RunSqlAction(sandbox=sandbox)])
    return AnalystLoop(system_prompt="sys", transport=transport, action_executor=executor, tool_specs=[_RUN_SQL_SPEC])


# --- parity scenarios --------------------------------------------------------

def test_parity_direct_answer(sandbox):
    old = _old_session(sandbox, _AnthropicClient([_reply([{"type": "text", "text": "respuesta directa"}])]))
    old_turn = old.ask("pregunta")

    result = _new_loop(sandbox, _AnthropicClient([_reply([{"type": "text", "text": "respuesta directa"}])])).ask("pregunta")

    assert old_turn.text == result.turn.text == "respuesta directa"
    assert old_turn.usage.calls == result.turn.usage.calls == 1


def test_parity_tool_then_answer(sandbox):
    script_fn = lambda: [_reply(_thinking_and_tool_use("c1", "SELECT 1 FROM dim_activo")), _reply([{"type": "text", "text": "con datos"}])]
    old = _old_session(sandbox, _AnthropicClient(script_fn()))
    old_turn = old.ask("pregunta")

    result = _new_loop(sandbox, _AnthropicClient(script_fn())).ask("pregunta")

    assert old_turn.text == result.turn.text == "con datos"
    assert old_turn.usage.calls == result.turn.usage.calls == 2
    assert [tc.args["query"] for tc in old_turn.tool_calls] == [tc.args["query"] for tc in result.turn.tool_calls] == ["SELECT 1 FROM dim_activo"]


def test_parity_four_investigation_rounds_then_synthesis(sandbox):
    script_fn = lambda: [
        *[_reply(_thinking_and_tool_use(str(i), f"SELECT {i} FROM dim_activo")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _reply([{"type": "text", "text": "conclusion sintetizada"}]),
    ]
    old = _old_session(sandbox, _AnthropicClient(script_fn()))
    old_turn = old.ask("pregunta que agota el presupuesto")

    new_client = _AnthropicClient(script_fn())
    result = _new_loop(sandbox, new_client).ask("pregunta que agota el presupuesto")

    assert old_turn.text == result.turn.text == "conclusion sintetizada"
    assert old_turn.usage.calls == result.turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    assert new_client.calls[-1]["tool_choice"] == {"type": "none"}
    for call in new_client.calls[:-1]:
        assert "tool_choice" not in call
    assert "no se alcanzo una respuesta final" not in result.turn.text


def test_parity_thinking_blocks_and_role_alternation_preserved(sandbox):
    """The critical Anthropic constraint. Inspects the RAW messages payload
    sent on round 2, not just Turn.text."""
    script_fn = lambda: [_reply(_thinking_and_tool_use("c1", "SELECT 1 FROM dim_activo")), _reply([{"type": "text", "text": "fin"}])]
    old_client = _AnthropicClient(script_fn())
    _old_session(sandbox, old_client).ask("pregunta")

    new_client = _AnthropicClient(script_fn())
    _new_loop(sandbox, new_client).ask("pregunta")

    old_messages = old_client.calls[1]["messages"]
    new_messages = new_client.calls[1]["messages"]

    old_roles = [m["role"] for m in old_messages]
    new_roles = [m["role"] for m in new_messages]
    assert old_roles == new_roles == ["user", "assistant", "user"]  # question, thinking+tool_use, tool_result

    old_thinking = [b for b in old_messages[1]["content"] if b.get("type") == "thinking"]
    new_thinking = [b for b in new_messages[1]["content"] if b.get("type") == "thinking"]
    assert old_thinking == new_thinking == [{"type": "thinking", "thinking": "razonando", "signature": "sig_c1"}]

    assert old_messages[2]["content"][0]["type"] == new_messages[2]["content"][0]["type"] == "tool_result"
    assert old_messages[2]["content"][0]["tool_use_id"] == new_messages[2]["content"][0]["tool_use_id"] == "c1"


def test_parity_synthesis_instruction_merges_into_trailing_tool_result_message(sandbox):
    """Old code's specific rule: the synthesis instruction rides on the
    existing tool_result user message instead of becoming a new user turn,
    because Anthropic requires strict role alternation and the trailing
    message before synthesis is always the tool_result one."""
    script_fn = lambda: [
        *[_reply(_thinking_and_tool_use(str(i), f"SELECT {i} FROM dim_activo")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _reply([{"type": "text", "text": "fin"}]),
    ]
    old_client = _AnthropicClient(script_fn())
    _old_session(sandbox, old_client).ask("pregunta")
    new_client = _AnthropicClient(script_fn())
    _new_loop(sandbox, new_client).ask("pregunta")

    old_final_messages = old_client.calls[-1]["messages"]
    new_final_messages = new_client.calls[-1]["messages"]
    assert old_final_messages[-1]["role"] == new_final_messages[-1]["role"] == "user"
    assert not any(a["role"] == b["role"] == "user" for a, b in zip(old_final_messages, old_final_messages[1:]))
    assert not any(a["role"] == b["role"] == "user" for a, b in zip(new_final_messages, new_final_messages[1:]))
    # last block on the trailing message is the synthesis instruction text
    from eval.benchmark.adapters.track_b_frontier import _SYNTHESIS_INSTRUCTION
    assert old_final_messages[-1]["content"][-1] == new_final_messages[-1]["content"][-1] == {"type": "text", "text": _SYNTHESIS_INSTRUCTION}


def test_parity_disobedient_provider_during_synthesis_is_ignored(sandbox):
    script_fn = lambda: [
        *[_reply(_thinking_and_tool_use(str(i), f"SELECT {i} FROM dim_activo")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _reply([{"type": "text", "text": "conclusion final"}, {"type": "tool_use", "id": "rogue", "name": "run_sql", "input": {"query": "SELECT 999"}}]),
    ]
    old_turn = _old_session(sandbox, _AnthropicClient(script_fn())).ask("pregunta")
    result = _new_loop(sandbox, _AnthropicClient(script_fn())).ask("pregunta")

    assert old_turn.text == result.turn.text == "conclusion final"
    assert len(old_turn.tool_calls) == len(result.turn.tool_calls) == MAX_INVESTIGATION_ROUNDS


def test_parity_provider_failure_propagates(sandbox):
    class _FailingClient:
        def __init__(self):
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError):
        _old_session(sandbox, _FailingClient()).ask("pregunta")
    with pytest.raises(RuntimeError):
        _new_loop(sandbox, _FailingClient()).ask("pregunta")
