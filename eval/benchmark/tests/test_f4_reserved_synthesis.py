"""F4 stage 1: the reserved final synthesis round.

Offline only -- every provider client here is a scripted stand-in, so no
network calls and no API spend. SQL execution inside the loop is real, against
the real pinned snapshot through the real sandbox, which is what lets these
tests assert that no query reaches the DB during the synthesis round.

What stage 1 changed, and what these tests pin down:

  before: 5 investigation rounds, no reserved synthesis. A model still asking
          for a tool on round 5 got its tool run and the turn returned
          "(no se alcanzo una respuesta final...)". 17 of B27's 79 Terra turns
          (21.5%) ended that way.
  after:  4 investigation rounds + 1 mandatory tool-free synthesis round.
          TOTAL model calls per turn is still 5 -- deliberately, so an F4 run
          stays compute-comparable with B26/B27 turn for turn.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.track_b_anthropic import _AnthropicSession
from eval.benchmark.adapters.track_b_frontier import (
    MAX_INVESTIGATION_ROUNDS,
    MAX_TOTAL_MODEL_ROUNDS,
    RESERVED_SYNTHESIS_ROUNDS,
    _SYNTHESIS_INSTRUCTION,
    _TrackBSession,
)
from eval.benchmark.adapters.track_b_openai_responses import _OpenAIResponsesSession
from eval.benchmark.snapshot import SnapshotSandbox

# A query that is valid, cheap, and unmistakable in the sandbox trace, so a
# synthesis round that wrongly executed a tool would be visible.
_SENTINEL_SQL = "SELECT 1 FROM dim_activo"


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def test_budget_constants_hold_total_at_five():
    """The methodological commitment: fix stopping without buying compute."""
    assert MAX_TOTAL_MODEL_ROUNDS == 5
    assert RESERVED_SYNTHESIS_ROUNDS == 1
    assert MAX_INVESTIGATION_ROUNDS == 4
    assert MAX_INVESTIGATION_ROUNDS + RESERVED_SYNTHESIS_ROUNDS == MAX_TOTAL_MODEL_ROUNDS


# --- Chat Completions (track_b_frontier) --------------------------------------

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


def _chat_session(sandbox, client) -> _TrackBSession:
    return _TrackBSession(sandbox=sandbox, session_id="f4", system_prompt="sys", client=client, model="test-model")


def _tool_call() -> _FakeToolCall:
    return _FakeToolCall(id="1", name="run_sql", arguments=json.dumps({"query": _SENTINEL_SQL}))


# Test 1 -- full exhaustion
def test_chat_exhaustion_runs_four_tool_rounds_then_synthesizes(sandbox):
    client = _ChatClient(script=[
        *[_chat_response(None, [_tool_call()]) for _ in range(MAX_INVESTIGATION_ROUNDS)],
        _chat_response("Conclusion con la evidencia disponible."),
    ])
    turn = _chat_session(sandbox, client).ask("pregunta que nunca se resuelve")

    assert len(client.calls) == MAX_TOTAL_MODEL_ROUNDS
    assert turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    # all four investigation rounds actually executed their tool
    assert len(turn.tool_calls) == MAX_INVESTIGATION_ROUNDS
    assert turn.text == "Conclusion con la evidencia disponible."
    assert "limite de iteraciones" not in turn.text
    # the synthesis round is the one that carries the instruction and no tools
    assert client.calls[-1][-1] == {"role": "user", "content": _SYNTHESIS_INSTRUCTION}
    assert client.calls_kwargs[-1]["tool_choice"] == "none"
    # ...and the investigation rounds were untouched
    for kwargs in client.calls_kwargs[:-1]:
        assert kwargs["tool_choice"] == "auto"


# Test 2 -- early conclusion
def test_chat_early_answer_uses_two_calls_and_no_synthesis(sandbox):
    client = _ChatClient(script=[
        _chat_response(None, [_tool_call()]),
        _chat_response("Respuesta en la segunda ronda."),
    ])
    turn = _chat_session(sandbox, client).ask("pregunta simple")

    assert len(client.calls) == 2
    assert turn.usage.calls == 2
    assert turn.text == "Respuesta en la segunda ronda."
    # no synthesis instruction anywhere -- the reserved round was never needed
    assert not any(_SYNTHESIS_INSTRUCTION in str(m) for call in client.calls for m in call)
    assert all(kwargs["tool_choice"] == "auto" for kwargs in client.calls_kwargs)


# Test 3 -- zero tools
def test_chat_direct_answer_uses_one_call_and_no_tools(sandbox):
    client = _ChatClient(script=[_chat_response("Respuesta directa, sin consultar nada.")])
    turn = _chat_session(sandbox, client).ask("hola")

    assert len(client.calls) == 1
    assert turn.usage.calls == 1
    assert turn.tool_calls == []
    assert turn.queries == []
    assert turn.text == "Respuesta directa, sin consultar nada."


# Test 4a -- tools are structurally unusable in the reserved round
def test_chat_synthesis_round_never_executes_a_tool_call(sandbox):
    """Defense in depth: even if a provider ignores tool_choice="none" and
    returns tool calls anyway, the synthesis branch never reads them, so no SQL
    can reach the sandbox from the reserved round."""
    client = _ChatClient(script=[
        *[_chat_response(None, [_tool_call()]) for _ in range(MAX_INVESTIGATION_ROUNDS)],
        # a disobedient provider: text AND another tool call on the final round
        _chat_response("Conclusion final.", [_FakeToolCall(id="99", name="run_sql",
                                                           arguments=json.dumps({"query": "SELECT 999"}))]),
    ])
    turn = _chat_session(sandbox, client).ask("pregunta")

    assert turn.text == "Conclusion final."
    assert len(turn.tool_calls) == MAX_INVESTIGATION_ROUNDS  # the 5th was ignored, not run
    assert not any("999" in q for q in turn.queries)


# Test 5 -- never a sixth round
@pytest.mark.parametrize("tool_rounds", list(range(MAX_INVESTIGATION_ROUNDS + 3)))
def test_chat_never_exceeds_total_budget(sandbox, tool_rounds):
    """Whatever the model does, total model calls stay within the fixed budget."""
    client = _ChatClient(script=[_chat_response(None, [_tool_call()]) for _ in range(tool_rounds)]
                         + [_chat_response("fin.") for _ in range(MAX_TOTAL_MODEL_ROUNDS + 2)])
    turn = _chat_session(sandbox, client).ask("pregunta")

    assert len(client.calls) <= MAX_TOTAL_MODEL_ROUNDS
    assert turn.usage.calls <= MAX_TOTAL_MODEL_ROUNDS
    assert "limite de iteraciones" not in turn.text


# --- OpenAI Responses (Terra / Sol) -------------------------------------------

@dataclass
class _ResponsesClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script[len(self.calls) - 1]


def _responses_reply(output, output_text=""):
    return SimpleNamespace(output=output, output_text=output_text,
                           usage=SimpleNamespace(input_tokens=None, output_tokens=None,
                                                 input_tokens_details=None, output_tokens_details=None))


def _responses_tool_item(call_id: str):
    # A reasoning item alongside the function call: this is the opaque payload
    # the Responses API requires echoed back on replay. If synthesis rebuilt the
    # input instead of appending to it, this would be dropped.
    return [
        {"type": "reasoning", "id": f"rs_{call_id}", "summary": []},
        {"type": "function_call", "call_id": call_id, "name": "run_sql",
         "arguments": json.dumps({"query": _SENTINEL_SQL})},
    ]


def _responses_session(sandbox, client) -> _OpenAIResponsesSession:
    return _OpenAIResponsesSession(sandbox, "f4", "system", client, "gpt-5.6-terra")


def test_responses_exhaustion_synthesizes_with_tools_disabled(sandbox):
    client = _ResponsesClient(script=[
        *[_responses_reply(_responses_tool_item(f"c{i}")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _responses_reply([{"type": "message", "content": [{"type": "output_text", "text": "Conclusion Terra."}]}],
                         "Conclusion Terra."),
    ])
    turn = _responses_session(sandbox, client).ask("pregunta que agota el presupuesto")

    assert len(client.calls) == MAX_TOTAL_MODEL_ROUNDS
    assert turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    assert turn.text == "Conclusion Terra."
    assert "limite de iteraciones" not in turn.text
    assert client.calls[-1]["tool_choice"] == "none"
    assert client.calls[-1]["input"][-1] == {"role": "user", "content": _SYNTHESIS_INSTRUCTION}


def test_responses_synthesis_preserves_reasoning_item_replay(sandbox):
    """The critical Terra/Sol constraint: the synthesis call must carry the full
    prior trajectory, opaque reasoning items included, not a rebuilt input."""
    client = _ResponsesClient(script=[
        *[_responses_reply(_responses_tool_item(f"c{i}")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _responses_reply([{"type": "message", "content": [{"type": "output_text", "text": "fin"}]}], "fin"),
    ])
    _responses_session(sandbox, client).ask("pregunta")

    final_input = client.calls[-1]["input"]
    reasoning_items = [i for i in final_input if isinstance(i, dict) and i.get("type") == "reasoning"]
    function_calls = [i for i in final_input if isinstance(i, dict) and i.get("type") == "function_call"]
    outputs = [i for i in final_input if isinstance(i, dict) and i.get("type") == "function_call_output"]
    assert len(reasoning_items) == MAX_INVESTIGATION_ROUNDS
    assert len(function_calls) == MAX_INVESTIGATION_ROUNDS
    assert len(outputs) == MAX_INVESTIGATION_ROUNDS
    # every function_call still has its matching call_id output
    assert {i["call_id"] for i in function_calls} == {i["call_id"] for i in outputs}


def test_responses_early_answer_makes_no_synthesis_call(sandbox):
    client = _ResponsesClient(script=[
        _responses_reply([{"type": "message", "content": [{"type": "output_text", "text": "directa"}]}], "directa"),
    ])
    turn = _responses_session(sandbox, client).ask("hola")

    assert len(client.calls) == 1
    assert turn.usage.calls == 1
    assert client.calls[0]["tool_choice"] == "auto"


# --- Anthropic ----------------------------------------------------------------

@dataclass
class _AnthropicClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script[len(self.calls) - 1]


def _anthropic_reply(blocks):
    # plain dicts: the adapter's _block_dict passes those through untouched
    return SimpleNamespace(content=list(blocks),
                           usage=SimpleNamespace(input_tokens=None, output_tokens=None))


def _anthropic_tool_blocks(block_id: str):
    # A thinking block travels with the tool_use block; it must survive replay.
    return [
        {"type": "thinking", "thinking": "razonando", "signature": f"sig_{block_id}"},
        {"type": "tool_use", "id": block_id, "name": "run_sql", "input": {"query": _SENTINEL_SQL}},
    ]


def _anthropic_session(sandbox, client) -> _AnthropicSession:
    return _AnthropicSession(sandbox, "f4", "system", client, "claude-sonnet-5")


def test_anthropic_exhaustion_synthesizes_with_tool_choice_none(sandbox):
    client = _AnthropicClient(script=[
        *[_anthropic_reply(_anthropic_tool_blocks(f"t{i}")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _anthropic_reply([{"type": "text", "text": "Conclusion Claude."}]),
    ])
    turn = _anthropic_session(sandbox, client).ask("pregunta que agota el presupuesto")

    assert len(client.calls) == MAX_TOTAL_MODEL_ROUNDS
    assert turn.usage.calls == MAX_TOTAL_MODEL_ROUNDS
    assert turn.text == "Conclusion Claude."
    assert "limite de iteraciones" not in turn.text
    assert client.calls[-1]["tool_choice"] == {"type": "none"}


def test_anthropic_synthesis_keeps_alternating_roles_and_thinking_blocks(sandbox):
    client = _AnthropicClient(script=[
        *[_anthropic_reply(_anthropic_tool_blocks(f"t{i}")) for i in range(MAX_INVESTIGATION_ROUNDS)],
        _anthropic_reply([{"type": "text", "text": "fin"}]),
    ])
    _anthropic_session(sandbox, client).ask("pregunta")

    final_messages = client.calls[-1]["messages"]
    roles = [m["role"] for m in final_messages]
    # no two consecutive user messages -- the instruction rode along on the
    # existing tool_result message instead of being appended as a new turn
    assert not any(a == b == "user" for a, b in zip(roles, roles[1:]))
    assert final_messages[-1]["role"] == "user"
    assert final_messages[-1]["content"][-1] == {"type": "text", "text": _SYNTHESIS_INSTRUCTION}
    # thinking blocks survived verbatim in the replayed assistant turns
    thinking = [b for m in final_messages if isinstance(m["content"], list)
                for b in m["content"] if isinstance(b, dict) and b.get("type") == "thinking"]
    assert len(thinking) == MAX_INVESTIGATION_ROUNDS
    assert all(b["signature"].startswith("sig_") for b in thinking)


def test_anthropic_early_answer_makes_no_synthesis_call(sandbox):
    client = _AnthropicClient(script=[_anthropic_reply([{"type": "text", "text": "directa"}])])
    turn = _anthropic_session(sandbox, client).ask("hola")

    assert len(client.calls) == 1
    assert turn.usage.calls == 1
    assert "tool_choice" not in client.calls[0]


# --- manifest pins the synthesis prompt ---------------------------------------

def test_manifest_fingerprints_the_reserved_synthesis_prompt():
    """The instruction is model-facing but lives outside the system prompt and
    outside the tool schema, so without its own hash a reworded synthesis would
    be invisible in the manifest. Pinned here the same way the frozen contract
    hashes are."""
    import hashlib

    from eval.round_b.runner import _reserved_synthesis_prompt_hash, build_run_manifest

    expected = hashlib.sha256(_SYNTHESIS_INSTRUCTION.encode("utf-8")).hexdigest()
    assert _reserved_synthesis_prompt_hash() == expected

    manifest = build_run_manifest("offline", "deadbeef", "2026-08-18T00:00:00Z")
    assert manifest["reserved_synthesis_prompt_sha256"] == expected
    # the pre-F4 contract hashes must stay untouched by stage 1
    assert manifest["system_prompt_sha256"] == "b155ded6464def5a8cf7ba8d4e9c56af8dc3b402cf0227b5f9f097ab96e17f44"
    assert manifest["tool_schema_sha256"] == "d5623b5fc7f1cbc35d6f75b69403df87bbb326c9995d8e240f6a5e51d1b196ca"


# --- placeholder is gone from every path --------------------------------------

def test_placeholder_string_is_absent_from_all_three_adapters():
    """The old exhaustion text must not survive anywhere as a normal outcome."""
    adapters_dir = Path(__file__).resolve().parents[1] / "adapters"
    for name in ("track_b_frontier.py", "track_b_openai_responses.py", "track_b_anthropic.py"):
        source = (adapters_dir / name).read_text(encoding="utf-8")
        assert "no se alcanzo una respuesta final" not in source, name
