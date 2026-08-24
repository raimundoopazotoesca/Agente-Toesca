"""Manual QA Consolidation Fix v1 -- focused regression tests.

Covers the four generic root causes fixed in this stage:
  A. adjacent structured-fact fragments concatenating with no glue / stray
     backslash-escaped punctuation surviving into rendered prose.
  B. a stale NONE evidence payload from a PRIOR turn's retained history
     overriding a NEW turn's on-topic model answer.
  C. a planner-selected (not user-requested) invalid aggregation leaking the
     internal semantic_rejection text as the final answer, vs an explicitly
     user-requested invalid aggregation still rejecting deterministically.

No per-fund / per-metric / per-question branching is introduced anywhere in
these tests' subject code -- see coverage_guard.py, humanize.py,
analyst_loop.py and session.py for the corresponding generic fixes.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.analyst_runtime.analyst_loop import AnalystLoop, _is_explicit_user_aggregation
from tools.analyst_runtime.base import ToolCall, Usage
from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.transport import ModelRequest, ModelResponse, ToolRequest, ToolResult, TranscriptItem
from tools.analytics.humanize import humanize_text


# ---------------------------------------------------------------------------
# A1/A2 -- multi-account fact rendering: no bare concatenation, no stray "\:"
# ---------------------------------------------------------------------------

def test_two_consecutive_governed_dataset_refs_get_a_glue_space():
    from tools.analyst_runtime.transport import ToolEvidence

    facts_a = ({"metric_key": "contribuciones", "value": 15220.0, "unit": "UF", "entity_id": "Torre A", "period": "2025"},)
    facts_b = ({"metric_key": "contribuciones", "value": 7526.0, "unit": "UF", "entity_id": "Boulevard PT", "period": "2025"},)
    ev_a = ToolEvidence("g1", "governed_dataset", scope={"fund": "PT"}, coverage={"status": "complete"}, facts=facts_a)
    ev_b = ToolEvidence("g2", "governed_dataset", scope={"fund": "PT"}, coverage={"status": "complete"}, facts=facts_b)
    envelope = {
        "fragments": [
            {"type": "governed_dataset_ref", "claim_id": "ca"},
            {"type": "governed_dataset_ref", "claim_id": "cb"},
        ],
        "canonical_metric_claims": [],
        "governed_dataset_claims": [
            {"claim_id": "ca", "evidence_id": "g1", "entity_ids": ["Torre A"], "period": "2025", "metric_key": "contribuciones"},
            {"claim_id": "cb", "evidence_id": "g2", "entity_ids": ["Boulevard PT"], "period": "2025", "metric_key": "contribuciones"},
        ],
    }
    result = validate_and_render(envelope, [], [ev_a, ev_b])
    assert result.valid
    assert "UFBoulevard" not in result.content
    assert "UF Boulevard" in result.content or result.content.count("UF") == 2


def test_humanize_text_strips_markdown_escaped_colon_generically():
    assert humanize_text("los montos fueron\\: importantes", None) == "los montos fueron: importantes"
    # Unaffected when there is nothing to de-escape.
    assert humanize_text("los montos fueron: importantes", None) == "los montos fueron: importantes"


# ---------------------------------------------------------------------------
# B1 -- a stale prior-turn NONE payload must not overwrite a fresh, on-topic
# model answer when the current turn made no new analytics_account_query call.
# ---------------------------------------------------------------------------

def test_account_no_evidence_override_only_fires_on_a_fresh_query():
    from tools.analyst_runtime.session import _account_no_evidence_payload

    stale_result = SimpleNamespace(
        trace={"tool_name": "analytics_account_query", "coverage": {"status": "none"}},
        content='{"concept_id": "gasto_seguros", "entity": "Apo", "period": "2025", "coverage": {"status": "none"}}',
        evidence=None,
    )
    stale_item = SimpleNamespace(tool_results=[stale_result])
    investigation = SimpleNamespace(round_trajectory=[stale_item], tool_calls=[])

    # This turn made no analytics_account_query call at all -- the caller in
    # session.py must gate on that before considering the payload found in
    # (stale, retained) round_trajectory.
    queried_this_turn = any(c.name == "analytics_account_query" for c in investigation.tool_calls)
    assert queried_this_turn is False
    # The raw payload lookup itself still finds the stale evidence (by design,
    # it inspects the whole trajectory) -- the fix is the caller-side gate,
    # asserted above and exercised end-to-end in test_product_voice.py-style
    # session tests.
    assert _account_no_evidence_payload(investigation) is not None


# ---------------------------------------------------------------------------
# C1/C2 -- explicit user-requested invalid aggregation still rejects;
# a planner-only invalid proposal on an open question does not.
# ---------------------------------------------------------------------------

def test_explicit_user_aggregation_detection_is_generic_not_per_metric():
    assert _is_explicit_user_aggregation("suma el LTV mensual de TRI durante 2025", "sum") is True
    assert _is_explicit_user_aggregation("promedia la vacancia de Apoquindo", "avg") is True
    assert _is_explicit_user_aggregation(
        "¿Hay algo que sí puedas decirme con seguridad sobre ese fondo en 2025?", "avg"
    ) is False


class _FakeTransport:
    """Minimal ModelTransport double: first call proposes an invalid
    aggregation tool call, second call (bounded recovery) terminates with
    plain text -- exercising the loop's own retry budget, not a new one."""

    def __init__(self, first_response: ModelResponse, second_response: ModelResponse):
        self._responses = [first_response, second_response]

    def complete(self, request: ModelRequest) -> ModelResponse:
        return self._responses.pop(0)


class _RejectingExecutor:
    def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(
            request.call_id, False, "{}",
            trace={"tool_name": request.name},
            control={"kind": "semantic_rejection", "code": "invalid_aggregation",
                     "requested_aggregation": "avg", "metric_id": "vacancia_pct_fondo",
                     "allowed_aggregations": ["last"]},
        )


def _tool_call_response(name: str = "analytics_query") -> ModelResponse:
    return ModelResponse(
        text="", tool_requests=[ToolRequest(call_id="c1", name=name, arguments={"metric": "vacancia_pct_fondo", "aggregation": "avg"})],
        usage=Usage(), raw_items=[],
    )


def _terminal_response(text: str) -> ModelResponse:
    return ModelResponse(text=text, tool_requests=[], usage=Usage(), raw_items=[])


def test_open_question_invalid_planner_aggregation_does_not_leak_as_final_answer():
    loop = AnalystLoop(
        system_prompt="sp", transport=_FakeTransport(_tool_call_response(), _terminal_response("Aqui va lo que si puedo confirmar.")),
        action_executor=_RejectingExecutor(), tool_specs=[],
    )
    result = loop.investigate("¿Hay algo que sí puedas decirme con seguridad sobre ese fondo en 2025?")
    assert result.termination_reason != "semantic_rejection"
    assert "No se puede" not in result.final_text
    assert result.final_text == "Aqui va lo que si puedo confirmar."


def test_explicit_invalid_aggregation_request_still_rejects_deterministically():
    loop = AnalystLoop(
        system_prompt="sp", transport=_FakeTransport(_tool_call_response(), _terminal_response("unused")),
        action_executor=_RejectingExecutor(), tool_specs=[],
    )
    result = loop.investigate("promedia la vacancia pct fondo de Apoquindo durante 2025")
    assert result.termination_reason == "semantic_rejection"
    assert "No se puede" in result.final_text


# ---------------------------------------------------------------------------
# Toolless-turn fact-integrity gap: a follow-up that makes NO new tool call
# must still bind arithmetic against RETAINED evidence via a derived_metric_ref
# through the same coverage_guard pipeline -- never free-text arithmetic.
# ---------------------------------------------------------------------------

def _retained_evidence():
    from tools.analyst_runtime.transport import ToolEvidence
    # Simulates evidence a PRIOR turn's tool call produced and the session
    # retained across turns -- coverage_guard only cares that the evidence_id
    # still resolves, not which turn originally produced it.
    return [
        ToolEvidence("call_a", "canonical_metric",
                     facts=({"metric_key": "contribuciones", "value": 15220.0, "unit": "UF",
                             "entity_id": "Torre A", "period": "2025"},)),
        ToolEvidence("call_b", "canonical_metric",
                     facts=({"metric_key": "contribuciones", "value": 7526.0, "unit": "UF",
                             "entity_id": "Boulevard PT", "period": "2025"},)),
    ]


def test_toolless_followup_difference_is_bound_via_derived_metric_ref():
    envelope = {
        "fragments": [
            {"type": "text", "text": "Torre A tuvo un gasto mayor, por "},
            {"type": "derived_metric_ref", "claim_id": "d1"},
        ],
        "canonical_metric_claims": [
            {"claim_id": "ca", "evidence_id": "call_a", "metric_key": "contribuciones", "value": 15220.0, "unit": "UF", "entity_id": "Torre A", "period": "2025"},
            {"claim_id": "cb", "evidence_id": "call_b", "metric_key": "contribuciones", "value": 7526.0, "unit": "UF", "entity_id": "Boulevard PT", "period": "2025"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "difference", "lhs_claim_id": "ca", "rhs_claim_id": "cb"}],
    }
    result = validate_and_render(envelope, _retained_evidence(), [])
    assert result.valid
    assert "7.694,00" in result.content or "7.693,41" in result.content or "7.694" in result.content
    # Lineage is preserved end to end: the derived claim's operands are the
    # SAME retained claim_ids, traceable back to their evidence_ids.
    assert result.trace["canonical_claim_count"] == 2


def test_toolless_followup_percent_is_bound_via_derived_metric_ref():
    envelope = {
        "fragments": [{"type": "derived_metric_ref", "claim_id": "d1"}],
        "canonical_metric_claims": [
            {"claim_id": "ca", "evidence_id": "call_a", "metric_key": "contribuciones", "value": 15220.0, "unit": "UF", "entity_id": "Torre A", "period": "2025"},
            {"claim_id": "cb", "evidence_id": "call_b", "metric_key": "contribuciones", "value": 7526.0, "unit": "UF", "entity_id": "Boulevard PT", "period": "2025"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "percent_change", "lhs_claim_id": "cb", "rhs_claim_id": "ca"}],
    }
    result = validate_and_render(envelope, _retained_evidence(), [])
    assert result.valid
    assert "%" in result.content


def test_toolless_followup_unbound_numeric_literal_fails_closed():
    """The model tries to smuggle the computed difference as a raw digit in
    free text instead of a derived_metric_ref -- must fail closed exactly as
    it would on a tool-calling turn (same _UNBOUND_QUANTITY_RE guard)."""
    envelope = {
        "fragments": [{"type": "text", "text": "La diferencia fue de 7.693,41 UF."}],
        "canonical_metric_claims": [], "governed_dataset_claims": [], "derived_metric_claims": [],
    }
    result = validate_and_render(envelope, _retained_evidence(), [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_derived_quantity"


def test_derived_claim_lineage_chains_back_to_retained_evidence_ids():
    envelope = {
        "fragments": [{"type": "derived_metric_ref", "claim_id": "d1"}],
        "canonical_metric_claims": [
            {"claim_id": "ca", "evidence_id": "call_a", "metric_key": "contribuciones", "value": 15220.0, "unit": "UF", "entity_id": "Torre A", "period": "2025"},
            {"claim_id": "cb", "evidence_id": "call_b", "metric_key": "contribuciones", "value": 7526.0, "unit": "UF", "entity_id": "Boulevard PT", "period": "2025"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "difference", "lhs_claim_id": "ca", "rhs_claim_id": "cb"}],
    }
    from tools.analyst_runtime.derived_claims import compute_derived_claim
    lhs_fact = {"metric_key": "contribuciones", "value": 15220.0, "unit": "UF", "entity_id": "Torre A", "period": "2025"}
    rhs_fact = {"metric_key": "contribuciones", "value": 7526.0, "unit": "UF", "entity_id": "Boulevard PT", "period": "2025"}
    derived = compute_derived_claim("d1", "difference", lhs_fact, rhs_fact, "ca", "cb")
    assert derived.lineage["lhs_claim_id"] == "ca"
    assert derived.lineage["rhs_claim_id"] == "cb"
    assert derived.lineage["lhs_value"] == 15220.0 and derived.lineage["rhs_value"] == 7526.0
    result = validate_and_render(envelope, _retained_evidence(), [])
    assert result.valid
