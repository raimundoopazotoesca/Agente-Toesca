"""Offline protocol tests for the direct OpenAI Responses adapter."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.track_b_openai_responses import TrackBOpenAIResponses, _OpenAIResponsesSession
from eval.benchmark.adapters.track_b_frontier import _RUN_SQL_TOOL
from eval.benchmark.snapshot import SnapshotSandbox
from eval.round_b.incremental import IncrementalStore
from eval.round_b.runner import live_adapter_factory
from eval.benchmark.adapters.track_b_frontier import resolve_b1_standard_profile


@dataclass
class _ResponsesClient:
    script: list
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.responses = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(AssertionError("Chat Completions must not be used"))))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script[len(self.calls) - 1]


def _response(output, output_text="", usage=None):
    return SimpleNamespace(output=output, output_text=output_text,
                           usage=usage or SimpleNamespace(input_tokens=None, output_tokens=None, input_tokens_details=None, output_tokens_details=None))


class _CapturingOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.responses = SimpleNamespace(create=lambda **_: None)


def test_direct_openai_client_disables_sdk_retries(monkeypatch):
    monkeypatch.setattr("eval.benchmark.adapters.track_b_openai_responses.OpenAI", _CapturingOpenAI)
    adapter = TrackBOpenAIResponses(provider={"api_key": "offline", "model": "gpt-5.6-terra"})
    assert adapter.client.kwargs["max_retries"] == 0


def test_live_factory_routes_terra_to_responses_adapter(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline")
    adapter = live_adapter_factory("openai", "gpt-5.6-terra", resolve_b1_standard_profile("openai", "gpt-5.6-terra"))
    assert isinstance(adapter, TrackBOpenAIResponses)


def test_terra_uses_responses_store_false_only_run_sql_and_native_defaults():
    sandbox = SnapshotSandbox()
    client = _ResponsesClient([_response([{"type": "message", "content": [{"type": "output_text", "text": "respuesta"}]}], "respuesta")])
    session = _OpenAIResponsesSession(sandbox, "s", "system", client, "gpt-5.6-terra")
    turn = session.ask("pregunta")
    request = client.calls[0]
    assert turn.text == "respuesta"
    assert request["store"] is False
    assert request["tools"] == [{"type": "function", "name": "run_sql", "description": _RUN_SQL_TOOL["function"]["description"], "parameters": _RUN_SQL_TOOL["function"]["parameters"]}]
    assert not ({"reasoning", "temperature", "top_p", "seed", "max_output_tokens", "previous_response_id", "conversation"} & request.keys())


def test_sol_replays_reasoning_function_call_and_function_output_in_memory(tmp_path):
    sandbox = SnapshotSandbox()
    private = "private-responses-reasoning"
    first_items = [
        {"type": "reasoning", "id": "rs_1", "encrypted_content": private},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "run_sql", "arguments": json.dumps({"query": "SELECT 1"})},
    ]
    usage = SimpleNamespace(input_tokens=11, output_tokens=7,
                            input_tokens_details=SimpleNamespace(cached_tokens=3),
                            output_tokens_details=SimpleNamespace(reasoning_tokens=5))
    client = _ResponsesClient([_response(first_items), _response([{"type": "message", "content": [{"type": "output_text", "text": "final"}]}], "final", usage)])
    session = _OpenAIResponsesSession(sandbox, "s", "system", client, "gpt-5.6-sol")
    turn = session.ask("pregunta")
    replay = client.calls[1]["input"]
    assert first_items[0] in replay
    assert first_items[1] in replay
    tool_output = next(item for item in replay if item.get("type") == "function_call_output")
    assert tool_output["call_id"] == "call_1"
    assert json.loads(tool_output["output"])["rows"] == [[1]]
    assert turn.usage.reasoning_tokens == 5
    assert private not in repr(turn.raw)

    store = IncrementalStore(tmp_path, "offline")
    store.turn({"final_answer": turn.text, "reasoning_tokens": turn.usage.reasoning_tokens, "response_items": first_items})
    store.event("provider_response_received", "openai", "case", 0, 0, 0, response_items=first_items)
    persisted = store.turns_path.read_text(encoding="utf-8") + store.events_path.read_text(encoding="utf-8")
    assert private not in persisted
    assert "reasoning_tokens" in persisted


def test_tce_keeps_response_items_in_memory_for_next_user_turn():
    sandbox = SnapshotSandbox()
    private = "private-tce-responses"
    prior = [{"type": "reasoning", "id": "rs_1", "encrypted_content": private},
             {"type": "message", "content": [{"type": "output_text", "text": "primera"}]}]
    client = _ResponsesClient([_response(prior, "primera"), _response([{"type": "message", "content": [{"type": "output_text", "text": "segunda"}]}], "segunda")])
    session = _OpenAIResponsesSession(sandbox, "tce", "system", client, "gpt-5.6-terra")
    session.ask("primera pregunta")
    session.ask("segunda pregunta")
    assert prior[0] in client.calls[1]["input"]
    assert private in repr(session.history)
