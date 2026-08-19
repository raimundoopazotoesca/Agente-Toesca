"""F4 Stage 2F, pre-cutover: multi-turn (TCE) golden parity between each Stage
1 session class (untouched) and AnalystLoop + its transport, driven through a
minimal compat wrapper that reproduces each provider's EXACT cross-turn
history policy -- verified by reading the legacy code directly, not assumed:

  Chat Completions (_TrackBSession):    self.history keeps ONLY
                                         [question, final_text] per turn --
                                         intermediate tool_calls/tool messages
                                         are discarded once a turn completes.
  Anthropic (_AnthropicSession):        same minimal truncation, but the
                                         retained assistant entry is a plain
                                         TEXT string (`final_text`), never the
                                         turn's raw content blocks -- thinking/
                                         tool_use blocks from a finished turn
                                         are never replayed into a later one.
  OpenAI Responses (_OpenAIResponsesSession): the OPPOSITE policy --
                                         `self.history = [*request_input,
                                         *final_items]`, i.e. the full raw
                                         trajectory (every reasoning item,
                                         every function_call/function_call_
                                         output pair, from every turn so far)
                                         is kept and replayed verbatim.

This is exactly the "wrapper decides retention" design analyst_loop.py's
module docstring describes. The `_CompatSession` classes below ARE the
pre-cutover shape of the real compatibility facades -- proven here against
scripted, offline clients before track_b_*.py's actual session classes are
rewritten to this same logic.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters._transport import ToolSpec, TranscriptItem
from eval.benchmark.adapters.actions import ActionRegistry, RunSqlAction
from eval.benchmark.adapters.analyst_loop import AnalystLoop
from eval.benchmark.adapters.track_b_anthropic import AnthropicTransport, _AnthropicSession
from eval.benchmark.adapters.track_b_frontier import ChatCompletionsTransport, _RUN_SQL_TOOL, _TrackBSession
from eval.benchmark.adapters.track_b_openai_responses import ResponsesTransport, _OpenAIResponsesSession
from eval.benchmark.snapshot import SnapshotSandbox

_RUN_SQL_SPEC = ToolSpec(name="run_sql", description=_RUN_SQL_TOOL["function"]["description"], parameters=_RUN_SQL_TOOL["function"]["parameters"])


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


# --- pre-cutover compat wrappers, one per provider's verified retention policy

@dataclass
class _ChatCompletionsCompatSession:
    """Chat Completions cross-turn policy: [question, final_text] only."""

    sandbox: SnapshotSandbox
    client: object
    model: str = "test-model"
    _compat_history: list[TranscriptItem] = field(default_factory=list)

    def ask(self, message: str):
        loop = AnalystLoop(
            system_prompt="sys",
            transport=ChatCompletionsTransport(client=self.client, model=self.model, tool_specs=[_RUN_SQL_SPEC]),
            action_executor=ActionRegistry([RunSqlAction(sandbox=self.sandbox)]),
            tool_specs=[_RUN_SQL_SPEC],
        )
        result = loop.ask(message, history=self._compat_history)
        self._compat_history = [*self._compat_history, TranscriptItem(role="user", text=message), TranscriptItem(role="assistant", text=result.turn.text)]
        return result.turn


@dataclass
class _AnthropicCompatSession:
    """Anthropic cross-turn policy: [question, final_text] only, text-only
    (no content blocks) for the retained assistant entry."""

    sandbox: SnapshotSandbox
    client: object
    model: str = "claude-sonnet-5"
    _compat_history: list[TranscriptItem] = field(default_factory=list)

    def ask(self, message: str):
        loop = AnalystLoop(
            system_prompt="sys",
            transport=AnthropicTransport(client=self.client, model=self.model, tool_specs=[_RUN_SQL_SPEC]),
            action_executor=ActionRegistry([RunSqlAction(sandbox=self.sandbox)]),
            tool_specs=[_RUN_SQL_SPEC],
        )
        result = loop.ask(message, history=self._compat_history)
        self._compat_history = [*self._compat_history, TranscriptItem(role="user", text=message), TranscriptItem(role="assistant", text=result.turn.text)]
        return result.turn


@dataclass
class _ResponsesCompatSession:
    """Responses cross-turn policy: the FULL raw trajectory, every turn."""

    sandbox: SnapshotSandbox
    client: object
    model: str = "gpt-5.6-terra"
    _compat_history: list[TranscriptItem] = field(default_factory=list)

    def ask(self, message: str):
        loop = AnalystLoop(
            system_prompt="sys",
            transport=ResponsesTransport(client=self.client, model=self.model, tool_specs=[_RUN_SQL_SPEC]),
            action_executor=ActionRegistry([RunSqlAction(sandbox=self.sandbox)]),
            tool_specs=[_RUN_SQL_SPEC],
        )
        result = loop.ask(message, history=self._compat_history)
        self._compat_history = result.round_trajectory
        return result.turn


# --- Chat Completions scripted helpers ---------------------------------------

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
    calls: list[list[dict]] = field(default_factory=list)

    def __post_init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        # Legacy sessions mutate `messages` in place across rounds within one
        # ask() call (same list object, repeated .append()); snapshot a
        # shallow copy so calls[i] reflects what was actually sent at call i,
        # not the turn's final state retroactively applied to every call.
        self.calls.append(list(messages))
        return self.script[len(self.calls) - 1]


def _chat_tool_call(query, call_id="1"):
    return _FakeToolCall(id=call_id, name="run_sql", arguments=json.dumps({"query": query}))


# --- Responses scripted helpers -----------------------------------------------

@dataclass
class _ResponsesClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        # Same in-place-mutation concern as _ChatClient, for `input`.
        self.calls.append({**kwargs, "input": list(kwargs["input"])})
        return self.script[len(self.calls) - 1]


def _resp(output, output_text=""):
    return SimpleNamespace(output=output, output_text=output_text,
                           usage=SimpleNamespace(input_tokens=None, output_tokens=None, input_tokens_details=None, output_tokens_details=None))


def _reasoning_and_call(call_id, query):
    return [{"type": "reasoning", "id": f"rs_{call_id}", "summary": []},
            {"type": "function_call", "call_id": call_id, "name": "run_sql", "arguments": json.dumps({"query": query})}]


def _message(text):
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


# --- Anthropic scripted helpers ------------------------------------------------

@dataclass
class _AnthropicClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        # Legacy Anthropic session mutates message content lists in place
        # (both tool_result appends and the trailing-message merge for the
        # synthesis instruction) -- a shallow copy of `messages` isn't enough
        # since the nested `content` lists are what gets mutated later.
        import copy
        self.calls.append({**kwargs, "messages": copy.deepcopy(kwargs["messages"])})
        return self.script[len(self.calls) - 1]


def _anthropic_reply(blocks):
    return SimpleNamespace(content=list(blocks), usage=SimpleNamespace(input_tokens=None, output_tokens=None))


def _thinking_and_tool_use(block_id, query):
    return [{"type": "thinking", "thinking": "razonando", "signature": f"sig_{block_id}"},
            {"type": "tool_use", "id": block_id, "name": "run_sql", "input": {"query": query}}]


# =============================================================================
# A. direct answer -> follow-up depending on prior context -> final
# =============================================================================

def test_chat_completions_scenario_a_two_direct_turns(sandbox):
    script = [_chat_response("TRI, PT y Apo"), _chat_response("PT es el mas grande")]
    old = _TrackBSession(sandbox=sandbox, session_id="a", system_prompt="sys", client=_ChatClient(list(script)), model="test-model")
    old_t1 = old.ask("que fondos hay")
    old_t2 = old.ask("cual es el mas grande")

    new = _ChatCompletionsCompatSession(sandbox=sandbox, client=_ChatClient(list(script)))
    new_t1 = new.ask("que fondos hay")
    new_t2 = new.ask("cual es el mas grande")

    assert (old_t1.text, old_t2.text) == (new_t1.text, new_t2.text) == ("TRI, PT y Apo", "PT es el mas grande")
    # after both turns, retained history holds exactly two [question, answer] pairs
    expected = [
        {"role": "user", "content": "que fondos hay"}, {"role": "assistant", "content": "TRI, PT y Apo"},
        {"role": "user", "content": "cual es el mas grande"}, {"role": "assistant", "content": "PT es el mas grande"},
    ]
    assert old.history == expected
    assert [{"role": i.role, "content": i.text} for i in new._compat_history] == old.history


def test_responses_scenario_a_two_direct_turns(sandbox):
    script = [_resp(_message("TRI, PT y Apo"), "TRI, PT y Apo"), _resp(_message("PT es el mas grande"), "PT es el mas grande")]
    old_client = _ResponsesClient(list(script))
    old = _OpenAIResponsesSession(sandbox, "a", "sys", old_client, "gpt-5.6-terra")
    old.ask("que fondos hay")
    old.ask("cual es el mas grande")

    new_client = _ResponsesClient(list(script))
    new = _ResponsesCompatSession(sandbox=sandbox, client=new_client)
    new.ask("que fondos hay")
    new.ask("cual es el mas grande")

    assert old_client.calls[1]["input"] == new_client.calls[1]["input"]


def test_anthropic_scenario_a_two_direct_turns(sandbox):
    script = [_anthropic_reply([{"type": "text", "text": "TRI, PT y Apo"}]), _anthropic_reply([{"type": "text", "text": "PT es el mas grande"}])]
    old = _AnthropicSession(sandbox, "a", "sys", _AnthropicClient(list(script)), "claude-sonnet-5")
    old.ask("que fondos hay")
    old.ask("cual es el mas grande")

    new = _AnthropicCompatSession(sandbox=sandbox, client=_AnthropicClient(list(script)))
    new.ask("que fondos hay")
    new.ask("cual es el mas grande")

    expected = [
        {"role": "user", "content": "que fondos hay"}, {"role": "assistant", "content": "TRI, PT y Apo"},
        {"role": "user", "content": "cual es el mas grande"}, {"role": "assistant", "content": "PT es el mas grande"},
    ]
    assert old.history == expected
    assert [{"role": i.role, "content": i.text} for i in new._compat_history] == old.history


# =============================================================================
# B. tool -> answer, then follow-up -> tool -> answer
# =============================================================================

def test_chat_completions_scenario_b_tool_turns(sandbox):
    script = [
        _chat_response(None, [_chat_tool_call("SELECT 1 FROM dim_activo")]), _chat_response("con datos t1"),
        _chat_response(None, [_chat_tool_call("SELECT 2 FROM dim_activo")]), _chat_response("con datos t2"),
    ]
    old_client = _ChatClient(list(script))
    old = _TrackBSession(sandbox=sandbox, session_id="b", system_prompt="sys", client=old_client, model="test-model")
    old_t1 = old.ask("pregunta 1")
    old_t2 = old.ask("pregunta 2 de seguimiento")

    new_client = _ChatClient(list(script))
    new = _ChatCompletionsCompatSession(sandbox=sandbox, client=new_client)
    new_t1 = new.ask("pregunta 1")
    new_t2 = new.ask("pregunta 2 de seguimiento")

    assert (old_t1.text, old_t2.text) == (new_t1.text, new_t2.text) == ("con datos t1", "con datos t2")
    assert [tc.args["query"] for tc in old_t2.tool_calls] == [tc.args["query"] for tc in new_t2.tool_calls] == ["SELECT 2 FROM dim_activo"]
    # turn 2's opening messages: system + [question1, answer1] history + tool-round messages -- no leaked tool_calls/tool messages from turn 1
    assert old_client.calls[2] == new_client.calls[2]
    assert old_client.calls[2][1] == {"role": "user", "content": "pregunta 1"}
    assert old_client.calls[2][2] == {"role": "assistant", "content": "con datos t1"}


def test_responses_scenario_b_tool_turns(sandbox):
    script = [
        _resp(_reasoning_and_call("t1c1", "SELECT 1 FROM dim_activo")), _resp(_message("con datos t1"), "con datos t1"),
        _resp(_reasoning_and_call("t2c1", "SELECT 2 FROM dim_activo")), _resp(_message("con datos t2"), "con datos t2"),
    ]
    old_client = _ResponsesClient(list(script))
    old = _OpenAIResponsesSession(sandbox, "b", "sys", old_client, "gpt-5.6-terra")
    old.ask("pregunta 1")
    old.ask("pregunta 2 de seguimiento")

    new_client = _ResponsesClient(list(script))
    new = _ResponsesCompatSession(sandbox=sandbox, client=new_client)
    new.ask("pregunta 1")
    new.ask("pregunta 2 de seguimiento")

    # turn 2's LAST call must replay turn 1's reasoning item verbatim
    old_final_input = old_client.calls[-1]["input"]
    new_final_input = new_client.calls[-1]["input"]
    assert old_final_input == new_final_input
    turn1_reasoning = [i for i in new_final_input if i.get("type") == "reasoning" and i.get("id") == "rs_t1c1"]
    assert len(turn1_reasoning) == 1


def test_anthropic_scenario_b_tool_turns(sandbox):
    script = [
        _anthropic_reply(_thinking_and_tool_use("t1c1", "SELECT 1 FROM dim_activo")), _anthropic_reply([{"type": "text", "text": "con datos t1"}]),
        _anthropic_reply(_thinking_and_tool_use("t2c1", "SELECT 2 FROM dim_activo")), _anthropic_reply([{"type": "text", "text": "con datos t2"}]),
    ]
    old_client = _AnthropicClient(list(script))
    old = _AnthropicSession(sandbox, "b", "sys", old_client, "claude-sonnet-5")
    old.ask("pregunta 1")
    old.ask("pregunta 2 de seguimiento")

    new_client = _AnthropicClient(list(script))
    new = _AnthropicCompatSession(sandbox=sandbox, client=new_client)
    new.ask("pregunta 1")
    new.ask("pregunta 2 de seguimiento")

    # turn 2's opening messages carry only the [question, text-answer] pair from turn 1 --
    # no thinking/tool_use blocks leak forward
    old_turn2_opening = old_client.calls[2]["messages"]
    new_turn2_opening = new_client.calls[2]["messages"]
    assert old_turn2_opening[:2] == new_turn2_opening[:2]
    assert old_turn2_opening[0] == {"role": "user", "content": "pregunta 1"}
    assert old_turn2_opening[1] == {"role": "assistant", "content": "con datos t1"}
    thinking_in_turn2_opening = [b for b in (old_turn2_opening[1]["content"] if isinstance(old_turn2_opening[1]["content"], list) else []) if b.get("type") == "thinking"]
    assert thinking_in_turn2_opening == []


# =============================================================================
# C. tool-heavy investigation -> synthesis, then follow-up about the conclusion
# =============================================================================

def test_responses_scenario_c_synthesis_then_followup(sandbox):
    """Highest-risk scenario: turn 1 exhausts the investigation budget and
    synthesizes; turn 2 must still replay turn 1's ENTIRE trajectory,
    including the synthesis instruction message and every reasoning item."""
    from eval.benchmark.adapters.analyst_loop import MAX_INVESTIGATION_ROUNDS

    t1_script = [_resp(_reasoning_and_call(str(i), f"SELECT {i} FROM dim_activo")) for i in range(MAX_INVESTIGATION_ROUNDS)]
    t1_script.append(_resp(_message("conclusion turno 1"), "conclusion turno 1"))
    t2_script = [_resp(_message("siguiendo la conclusion anterior"), "siguiendo la conclusion anterior")]
    script = t1_script + t2_script

    old_client = _ResponsesClient(list(script))
    old = _OpenAIResponsesSession(sandbox, "c", "sys", old_client, "gpt-5.6-terra")
    old.ask("investigacion pesada")
    old_t2 = old.ask("y que sigue de esa conclusion")

    new_client = _ResponsesClient(list(script))
    new = _ResponsesCompatSession(sandbox=sandbox, client=new_client)
    new.ask("investigacion pesada")
    new_t2 = new.ask("y que sigue de esa conclusion")

    assert old_t2.text == new_t2.text == "siguiendo la conclusion anterior"
    assert old_client.calls[-1]["input"] == new_client.calls[-1]["input"]
    reasoning_ids = {i["id"] for i in new_client.calls[-1]["input"] if i.get("type") == "reasoning"}
    assert reasoning_ids == {f"rs_{i}" for i in range(MAX_INVESTIGATION_ROUNDS)}


def test_chat_completions_scenario_c_synthesis_then_followup(sandbox):
    from eval.benchmark.adapters.analyst_loop import MAX_INVESTIGATION_ROUNDS

    t1_script = [_chat_response(None, [_chat_tool_call(f"SELECT {i} FROM dim_activo", str(i))]) for i in range(MAX_INVESTIGATION_ROUNDS)]
    t1_script.append(_chat_response("conclusion turno 1"))
    t2_script = [_chat_response("siguiendo la conclusion anterior")]
    script = t1_script + t2_script

    old_client = _ChatClient(list(script))
    old = _TrackBSession(sandbox=sandbox, session_id="c", system_prompt="sys", client=old_client, model="test-model")
    old.ask("investigacion pesada")
    old_t2 = old.ask("y que sigue de esa conclusion")

    new_client = _ChatClient(list(script))
    new = _ChatCompletionsCompatSession(sandbox=sandbox, client=new_client)
    new.ask("investigacion pesada")
    new_t2 = new.ask("y que sigue de esa conclusion")

    assert old_t2.text == new_t2.text == "siguiendo la conclusion anterior"
    # turn 2 opens with only [question, final_text] from turn 1 -- no synthesis-round tool leakage
    assert old_client.calls[-1] == new_client.calls[-1]
    assert old_client.calls[-1][1] == {"role": "user", "content": "investigacion pesada"}
    assert old_client.calls[-1][2] == {"role": "assistant", "content": "conclusion turno 1"}


def test_anthropic_scenario_c_synthesis_then_followup(sandbox):
    from eval.benchmark.adapters.analyst_loop import MAX_INVESTIGATION_ROUNDS

    t1_script = [_anthropic_reply(_thinking_and_tool_use(str(i), f"SELECT {i} FROM dim_activo")) for i in range(MAX_INVESTIGATION_ROUNDS)]
    t1_script.append(_anthropic_reply([{"type": "text", "text": "conclusion turno 1"}]))
    t2_script = [_anthropic_reply([{"type": "text", "text": "siguiendo la conclusion anterior"}])]
    script = t1_script + t2_script

    old_client = _AnthropicClient(list(script))
    old = _AnthropicSession(sandbox, "c", "sys", old_client, "claude-sonnet-5")
    old.ask("investigacion pesada")
    old_t2 = old.ask("y que sigue de esa conclusion")

    new_client = _AnthropicClient(list(script))
    new = _AnthropicCompatSession(sandbox=sandbox, client=new_client)
    new.ask("investigacion pesada")
    new_t2 = new.ask("y que sigue de esa conclusion")

    assert old_t2.text == new_t2.text == "siguiendo la conclusion anterior"
    assert old_client.calls[-1]["messages"] == new_client.calls[-1]["messages"]
    assert old_client.calls[-1]["messages"][0] == {"role": "user", "content": "investigacion pesada"}
    assert old_client.calls[-1]["messages"][1] == {"role": "assistant", "content": "conclusion turno 1"}
