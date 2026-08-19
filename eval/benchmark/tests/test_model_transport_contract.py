"""Shape tests for the F4 Stage 2 transport contract. No provider calls --
these just pin the dataclasses' fields so a later refactor can't silently
drop one (e.g. `raw_items` on ModelResponse, without which Responses/Anthropic
replay breaks).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters._transport import (
    ModelRequest,
    ModelResponse,
    ModelTransport,
    ToolRequest,
    ToolResult,
    ToolSpec,
    TranscriptItem,
)
from eval.benchmark.adapters.base import Usage


def test_tool_spec_shape():
    spec = ToolSpec(name="run_sql", description="run a query", parameters={"type": "object"})
    assert spec.name == "run_sql"


def test_tool_request_and_result_roundtrip_shape():
    req = ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT 1"})
    res = ToolResult(call_id="1", ok=True, content='{"columns": [], "rows": []}')
    assert req.call_id == res.call_id


def test_transcript_item_defaults_have_no_raw():
    item = TranscriptItem(role="user", text="hola")
    assert item.raw is None
    assert item.tool_requests == []
    assert item.tool_results == []


def test_transcript_item_can_carry_opaque_raw_for_replay():
    opaque = [{"type": "reasoning", "id": "rs_1"}]
    item = TranscriptItem(role="assistant", raw=opaque)
    assert item.raw is opaque


def test_model_request_empty_tools_means_synthesis_round():
    """No separate mode flag -- tools=[] IS how AnalystLoop tells a transport
    "no more investigation this round"."""
    request = ModelRequest(system_prompt="sys", history=[], message="msg", tools=[])
    assert request.tools == []


def test_model_response_defaults_are_a_plain_final_answer():
    resp = ModelResponse(text="la respuesta")
    assert resp.tool_requests == []
    assert resp.raw_items is None
    assert isinstance(resp.usage, Usage)


def test_model_response_can_carry_tool_requests_and_raw_items():
    resp = ModelResponse(
        text="",
        tool_requests=[ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT 1"})],
        raw_items=[{"type": "function_call", "call_id": "1"}],
    )
    assert resp.tool_requests[0].name == "run_sql"
    assert resp.raw_items[0]["call_id"] == "1"


def test_model_transport_is_a_structural_protocol():
    class _Fake:
        def complete(self, request: ModelRequest) -> ModelResponse:
            return ModelResponse(text="ok")

    transport: ModelTransport = _Fake()
    result = transport.complete(ModelRequest(system_prompt="", history=[], message="", tools=[]))
    assert result.text == "ok"
