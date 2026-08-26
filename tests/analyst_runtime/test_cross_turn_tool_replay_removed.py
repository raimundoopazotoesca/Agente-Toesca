"""P0: successful historical tool traces (function_call/function_call_output/
call_id) must not survive a completed turn boundary into the next turn's
planner input, while remaining fully available within the SAME investigation
for same-turn tool chaining, and while evidence-backed facts remain reusable
for legitimate follow-ups.
"""
from __future__ import annotations

from dataclasses import replace

from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession, OpenAIResponsesTransport
from tools.analyst_runtime.transport import ModelResponse, ToolEvidence, ToolRequest, ToolResult

FINANCIAL_FACT = {
    "metric_key": "ltv_fondo", "value": 61.02, "unit": "%", "entity_id": "TRI", "period": "2026-06",
    "space_type": None, "space_types": None, "measurement_unit": None,
}
TENANT_FACTS = (
    {"metric_key": "gla", "value": 1200.0, "unit": "m2", "entity_id": "Tenant A", "period": "2026-06",
     "space_type": None, "space_types": None, "measurement_unit": None},
)
FINANCIAL = ToolEvidence("financial", "canonical_metric", facts=(FINANCIAL_FACT,))
TENANTS = ToolEvidence("tenants", "governed_dataset",
                        coverage={"status": "complete", "observed_count": 1, "eligible_count": 1,
                                  "universe_kind": "asset_tenants"}, facts=TENANT_FACTS)


def _financial_envelope():
    return {"fragments": [{"type": "canonical_metric_ref", "claim_id": "f"}],
            "canonical_metric_claims": [{"claim_id": "f", "evidence_id": "financial-0", **FINANCIAL_FACT}],
            "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": []}


def _tenant_envelope():
    return {"fragments": [{"type": "text", "text": "Top arrendatarios: "},
                           {"type": "governed_dataset_ref", "claim_id": "t"}],
            "canonical_metric_claims": [],
            "governed_dataset_claims": [{"claim_id": "t", "evidence_id": "dataset-1", "metric_key": "gla",
                                          "entity_ids": ["Tenant A"], "period": "2026-06",
                                          "universe_kind": "asset_tenants"}],
            "derived_metric_claims": [], "table_claims": []}


class _Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return next(self.responses)


class _Executor:
    def execute(self, request):
        evidence = FINANCIAL if request.name == "financial" else TENANTS
        return ToolResult(request.call_id, True, "{}", evidence=replace(evidence, evidence_id=request.call_id))


def _raw_function_call(call_id: str, name: str) -> list[dict]:
    """Shape of a real OpenAI Responses `function_call` output item -- the
    opaque payload AnalystLoop stores in TranscriptItem.raw and replays
    verbatim on the next model call (see transport.py's module docstring)."""
    return [{"type": "function_call", "call_id": call_id, "name": name, "arguments": "{}"}]


def test_same_turn_tool_chaining_still_sees_raw_function_call_and_output():
    """WITHIN one investigation, a second round must still see round one's
    raw function_call/function_call_output -- the loop's normal reasoning
    chain must be untouched."""
    transport = _Transport([
        ModelResponse("", [ToolRequest("financial-0", "financial", {})],
                      raw_items=_raw_function_call("financial-0", "financial")),
        ModelResponse("Investigación terminada."),
        ModelResponse("ok", structured_output=_financial_envelope()),
    ])
    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", transport, _Executor()), presenter=None)

    session.ask("¿Cuál fue el LTV de TRI?")

    round_two_request = transport.requests[1]
    rendered = OpenAIResponsesTransport._render_history(round_two_request.history)
    assert any(entry.get("type") == "function_call" and entry.get("call_id") == "financial-0" for entry in rendered)
    assert any(entry.get("type") == "function_call_output" and entry.get("call_id") == "financial-0" for entry in rendered)


def test_multi_tool_same_turn_chaining_sees_both_prior_rounds_raw_trace():
    """Mandatory test C: a turn needing two distinct tool rounds must see
    BOTH prior rounds' raw function_call/function_call_output while still
    investigating -- no regression in same-turn multi-tool reasoning."""
    transport = _Transport([
        ModelResponse("", [ToolRequest("financial-0", "financial", {})],
                      raw_items=_raw_function_call("financial-0", "financial")),
        ModelResponse("", [ToolRequest("dataset-1", "dataset", {})],
                      raw_items=_raw_function_call("dataset-1", "dataset")),
        ModelResponse("Investigación terminada."),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "canonical_metric_ref", "claim_id": "f"},
                          {"type": "governed_dataset_ref", "claim_id": "t"}],
            "canonical_metric_claims": [{"claim_id": "f", "evidence_id": "financial-0", **FINANCIAL_FACT}],
            "governed_dataset_claims": [{"claim_id": "t", "evidence_id": "dataset-1", "metric_key": "gla",
                                          "entity_ids": ["Tenant A"], "period": "2026-06",
                                          "universe_kind": "asset_tenants"}],
            "derived_metric_claims": [], "table_claims": [],
        }),
    ])
    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", transport, _Executor()), presenter=None)

    session.ask("LTV de TRI y top arrendatarios de Apo3001.")

    round_three_request = transport.requests[2]
    rendered = OpenAIResponsesTransport._render_history(round_three_request.history)
    call_ids_present = {entry.get("call_id") for entry in rendered if entry.get("type") == "function_call"}
    assert call_ids_present == {"financial-0", "dataset-1"}
    output_ids_present = {entry.get("call_id") for entry in rendered if entry.get("type") == "function_call_output"}
    assert output_ids_present == {"financial-0", "dataset-1"}


def test_completed_turn_boundary_strips_raw_function_call_trace_from_next_turn():
    """P0: a SUCCESSFUL turn's raw tool trace must not survive into the next
    turn's planner input -- this is the recency-bias root cause. The
    accepted fact (ToolEvidence) must still be reachable for follow-ups."""
    transport = _Transport([
        ModelResponse("", [ToolRequest("financial-0", "financial", {})],
                      raw_items=_raw_function_call("financial-0", "financial")),
        ModelResponse("Investigación terminada."),
        ModelResponse("ok", structured_output=_financial_envelope()),
        ModelResponse("", [ToolRequest("dataset-1", "dataset", {})],
                      raw_items=_raw_function_call("dataset-1", "dataset")),
        ModelResponse("Investigación terminada."),
        ModelResponse("ok", structured_output=_tenant_envelope()),
    ])
    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", transport, _Executor()), presenter=None)

    session.ask("¿Cuál fue el LTV de TRI?")
    boundary = len(transport.requests)
    session.ask("Top 5 arrendatarios por GLA de Apo3001.")

    first_request_of_second_turn = transport.requests[boundary]
    rendered = OpenAIResponsesTransport._render_history(first_request_of_second_turn.history)
    assert not any(entry.get("type") in {"function_call", "function_call_output"} for entry in rendered)
    assert not any(entry.get("call_id") == "financial-0" for entry in rendered)
    assert all(not item.raw for item in first_request_of_second_turn.history)
    assert all(not item.tool_requests for item in first_request_of_second_turn.history)
    # The accepted fact must still be reachable through the normalized
    # evidence mechanism (not through wire replay) for a later follow-up.
    assert any(
        result.evidence is not None and result.evidence.evidence_id == "financial-0"
        for item in first_request_of_second_turn.history
        for result in item.tool_results
    )
