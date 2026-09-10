"""Governed Analytics Expansion v1: contracts, coverage and period binding.

Offline reproductions of the Alpha eval cases that exercise the governed
path (02, 03, 05, 06, 07, 08, 12) at component level -- no provider calls.
"""
import json
from pathlib import Path

import pytest

from tools.analyst_runtime.actions import (
    AnalyticsBreakdownAssetAction, AnalyticsLookupAssetAction, AnalyticsLookupFundAction,
    ListAssetsAction,
)
from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.transport import ToolRequest

DB = Path("memory/agente_toesca_v2.db")


def _run(action, args, call_id="call"):
    return action.execute(ToolRequest(call_id, action.name, args))


# --------------------------------------------------------------- case 02/12

def test_case02_asset_ltv_lookup_is_canonical_evidence_with_raw_ratio():
    result = _run(AnalyticsLookupAssetAction(DB), {
        "metric": "ltv_activo", "assets": ["Apo3001"], "period": "2026-06", "period_end": None})

    assert result.ok
    assert result.evidence.evidence_class == "canonical_metric"
    fact = result.evidence.facts[0]
    assert fact["entity_id"] == "Apo3001"
    assert fact["unit"] == "ratio_0_1"
    assert fact["value"] == pytest.approx(0.7115159, rel=1e-6)


def test_case02_asset_ltv_renders_as_percent_only_after_binding():
    result = _run(AnalyticsLookupAssetAction(DB), {
        "metric": "ltv_activo", "assets": ["Apo3001"], "period": "2026-06", "period_end": None}, "e1")
    fact = result.evidence.facts[0]
    envelope = {
        "fragments": [{"type": "text", "text": "El LTV es "}, {"type": "canonical_metric_ref", "claim_id": "c"}],
        "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", **fact}],
        "governed_dataset_claims": [],
    }
    validation = validate_and_render(envelope, [result.evidence], [])

    assert validation.valid
    assert validation.content == "El LTV es 71,15%"


def test_case12_fund_ltv_lookup_distinguishes_tri_from_pt():
    action = AnalyticsLookupFundAction(DB)
    tri = _run(action, {"metric": "ltv_fondo", "fund": "TRI", "period": "2026-06", "period_end": None})
    pt = _run(action, {"metric": "ltv_fondo", "fund": "PT", "period": "2026-06", "period_end": None})

    assert tri.evidence.facts[0]["value"] == pytest.approx(0.6101647, rel=1e-6)
    assert pt.evidence.facts[0]["value"] == pytest.approx(0.8122455, rel=1e-6)


# ------------------------------------------------------------------ case 03

def test_case03_previous_month_lookup_binds_the_requested_month():
    result = _run(AnalyticsLookupAssetAction(DB), {
        "metric": "ltv_activo", "assets": ["Apo3001"], "period": "2026-05", "period_end": None})
    assert result.evidence.facts[0]["period"] == "2026-05"
    assert result.evidence.evidence_class == "canonical_metric"


# --------------------------------------------------------------- case 08/10

def test_multi_period_scalar_becomes_period_range_governed_dataset():
    """Previously this produced evidence=None and the datum was silently
    dropped (the case-08 bug)."""
    result = _run(AnalyticsLookupAssetAction(DB), {
        "metric": "ltv_activo", "assets": ["Apo3001"], "period": "2024-10", "period_end": "2026-06"}, "e1")

    assert result.evidence is not None
    assert result.evidence.evidence_class == "governed_dataset"
    assert result.evidence.coverage["universe_kind"] == "period_range"
    assert result.evidence.semantic_contract["universe_kind"] == "period_range"
    periods = [fact["period"] for fact in result.evidence.facts]
    assert len(periods) == len(set(periods)) > 1
    assert {fact["entity_id"] for fact in result.evidence.facts} == {"Apo3001"}


def _period_range_evidence():
    return _run(AnalyticsLookupAssetAction(DB), {
        "metric": "ltv_activo", "assets": ["Apo3001"], "period": "2024-10", "period_end": "2026-06"}, "e1").evidence


def _series_envelope(period):
    return {
        "fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}],
        "canonical_metric_claims": [],
        "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "e1", "metric_key": "ltv_activo",
                                     "entity_ids": ["Apo3001"], "period": period, "universe_kind": "period_range"}],
    }


def test_period_range_claim_binds_the_exact_requested_month():
    evidence = _period_range_evidence()
    validation = validate_and_render(_series_envelope("2026-06"), [], [evidence])

    assert validation.valid
    assert validation.content == "Apo3001: 71,15%"


def test_period_range_claim_for_an_absent_month_fails_closed():
    evidence = _period_range_evidence()
    validation = validate_and_render(_series_envelope("2019-01"), [], [evidence])

    assert not validation.valid
    assert validation.trace["reason"] == "binding_mismatch"
    # Never a wrong-period default.
    assert "71.15%" not in validation.content


def test_period_range_claim_never_defaults_to_the_first_point_of_the_series():
    evidence = _period_range_evidence()
    first = evidence.facts[0]
    assert first["period"] != "2026-06"
    validation = validate_and_render(_series_envelope("2026-06"), [], [evidence])
    assert f"{first['value'] * 100:.2f}%" not in validation.content


# ------------------------------------------------------------------ case 06

def test_case06_full_fund_ranking_reports_partial_coverage():
    result = _run(AnalyticsBreakdownAssetAction(DB), {
        "metric": "noi_mensual_activo", "fund": "TRI", "assets": None, "period": "2026-06",
        "period_end": None, "order_by": "value_desc", "limit": None})

    coverage = result.evidence.coverage
    assert coverage["universe_kind"] == "fund_assets"
    assert coverage["status"] == "partial"
    assert coverage["observed_count"] == 4
    assert coverage["eligible_count"] > coverage["observed_count"]
    assert [fact["entity_id"] for fact in result.evidence.facts][0] == "Viña Centro"


# ------------------------------------------------------------------ case 07

def test_case07_explicit_subset_ranking_is_complete_over_the_subset():
    result = _run(AnalyticsBreakdownAssetAction(DB), {
        "metric": "noi_mensual_activo", "fund": "TRI",
        "assets": ["INMOSA", "Viña Centro", "Mall Curicó"], "period": "2026-06",
        "period_end": None, "order_by": "value_desc", "limit": None}, "e1")

    coverage = result.evidence.coverage
    assert coverage["universe_kind"] == "explicit_subset"
    assert coverage["status"] == "complete"
    assert coverage["eligible_count"] == 3
    assert [fact["entity_id"] for fact in result.evidence.facts] == ["Viña Centro", "INMOSA", "Mall Curicó"]


def test_explicit_subset_member_without_a_kpi_row_makes_coverage_partial():
    """A member that belongs to the fund but has no KPI row stays in the
    expected universe -- it is never silently dropped."""
    result = _run(AnalyticsBreakdownAssetAction(DB), {
        "metric": "noi_mensual_activo", "fund": "TRI",
        "assets": ["INMOSA", "Apo3001"], "period": "2026-06",
        "period_end": None, "order_by": "value_desc", "limit": None})

    coverage = result.evidence.coverage
    assert coverage["status"] == "partial"
    assert coverage["eligible_ids"] == ["Apo3001", "INMOSA"]
    assert coverage["observed_ids"] == ["INMOSA"]


def test_subset_member_outside_the_fund_is_rejected():
    result = _run(AnalyticsBreakdownAssetAction(DB), {
        "metric": "noi_mensual_activo", "fund": "TRI", "assets": ["Torre A"],
        "period": "2026-06", "period_end": None, "order_by": None, "limit": None})

    assert not result.ok
    payload = json.loads(result.content)
    assert payload["error_type"] == "semantic_query_error"
    assert "Torre A" in payload["error"]


def test_subset_member_outside_its_temporal_applicability_is_rejected():
    result = _run(AnalyticsBreakdownAssetAction(DB), {
        "metric": "noi_mensual_activo", "fund": "TRI", "assets": ["Strip Machalí"],
        "period": "2026-06", "period_end": None, "order_by": None, "limit": None})

    assert not result.ok
    assert json.loads(result.content)["error_type"] == "semantic_query_error"


# ------------------------------------------------------------------ case 05

def test_case05_list_assets_enumerates_the_fund_and_marks_divested_assets():
    result = _run(ListAssetsAction(DB), {"fund": "TRI", "period": None})

    assert result.ok
    payload = json.loads(result.content)
    keys = [asset["entity_id"] for asset in payload["assets"]]
    assert "Strip Machalí" in keys
    machali = next(a for a in payload["assets"] if a["entity_id"] == "Strip Machalí")
    assert machali["vigente_hasta"] == "2025-08"
    assert machali["applicable"] is False
    assert result.evidence.evidence_class == "governed_dataset"
    assert result.evidence.coverage["status"] == "complete"
    assert "Strip Machalí" not in result.evidence.coverage["eligible_ids"]


def test_list_assets_with_a_period_uses_the_universe_applicable_then():
    now = _run(ListAssetsAction(DB), {"fund": "TRI", "period": None})
    then = _run(ListAssetsAction(DB), {"fund": "TRI", "period": "2025-06"})

    assert "Strip Machalí" in then.evidence.coverage["eligible_ids"]
    assert "Strip Machalí" not in now.evidence.coverage["eligible_ids"]
    assert then.evidence.coverage["eligible_count"] == now.evidence.coverage["eligible_count"] + 1
    assert then.evidence.coverage["status"] == "complete"


def test_list_assets_rejects_an_unknown_fund():
    result = _run(ListAssetsAction(DB), {"fund": "NO_EXISTE", "period": None})
    assert not result.ok
    assert json.loads(result.content)["error_type"] == "semantic_query_error"


def test_list_assets_backs_a_multi_entity_enumeration_in_free_text():
    """The entity-provenance guard must accept an enumeration backed by
    list_assets evidence."""
    result = _run(ListAssetsAction(DB), {"fund": "TRI", "period": None}, "e1")
    entity_ids = [fact["entity_id"] for fact in result.evidence.facts]
    envelope = {
        "fragments": [{"type": "text", "text": "Los activos son " + ", ".join(entity_ids) + "."}],
        "canonical_metric_claims": [],
        "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "e1", "metric_key": None,
                                     "entity_ids": entity_ids, "period": None,
                                     "universe_kind": "fund_assets"}],
    }
    validation = validate_and_render(envelope, [], [result.evidence], DB)
    assert validation.valid


# ------------------------------------------------- multi-asset lookup shape

def test_multi_asset_lookup_is_a_breakdown_over_the_named_assets():
    result = _run(AnalyticsLookupAssetAction(DB), {
        "metric": "ltv_activo", "assets": ["Apo3001", "INMOSA"], "period": "2026-06", "period_end": None})

    assert result.evidence.evidence_class == "governed_dataset"
    assert {fact["entity_id"] for fact in result.evidence.facts} == {"Apo3001", "INMOSA"}
    assert result.evidence.coverage["universe_kind"] == "explicit_subset"
    assert result.evidence.coverage["status"] == "complete"


def test_lookup_rejects_a_repeated_or_empty_asset_list():
    action = AnalyticsLookupAssetAction(DB)
    for assets in ([], ["Apo3001", "Apo3001"]):
        result = _run(action, {"metric": "ltv_activo", "assets": assets,
                               "period": "2026-06", "period_end": None})
        assert not result.ok
        assert json.loads(result.content)["error_type"] == "invalid_request"


# ------------------------- canonical claims selecting one governed fact -----

def _canonical_claim_envelope(claim, text_before="El valor es "):
    return {
        "fragments": [{"type": "text", "text": text_before},
                      {"type": "canonical_metric_ref", "claim_id": "c"}],
        "canonical_metric_claims": [{"claim_id": "c", **claim}],
        "governed_dataset_claims": [],
    }


def test_canonical_claim_can_select_one_period_from_a_series():
    evidence = _period_range_evidence()
    fact = next(f for f in evidence.facts if f["period"] == "2026-06")
    validation = validate_and_render(_canonical_claim_envelope({"evidence_id": "e1", **fact}), [], [evidence])

    assert validation.valid
    assert validation.content == "El valor es 71,15%"


def test_canonical_claim_selecting_a_wrong_period_value_fails_closed():
    evidence = _period_range_evidence()
    fact = next(f for f in evidence.facts if f["period"] == "2026-06")
    other = next(f for f in evidence.facts if f["period"] != "2026-06")
    claim = {"evidence_id": "e1", **fact, "value": other["value"]}
    validation = validate_and_render(_canonical_claim_envelope(claim), [], [evidence])

    assert not validation.valid
    assert validation.trace["reason"] == "binding_mismatch"


def test_canonical_claim_with_a_wrong_unit_fails_closed():
    """A3.2f: the generic binding_mismatch equality check covers `unit`
    among its 8 compared fields (coverage_guard.validate_and_render), but no
    prior test isolated unit specifically -- only period/entity/value had
    dedicated regressions. `unit` is one of the two rendered, consequence-
    bearing fields (with `value`), so it deserves its own regression rather
    than only implicit coverage via the period-mismatch test above."""
    evidence = _period_range_evidence()
    fact = next(f for f in evidence.facts if f["period"] == "2026-06")
    claim = {"evidence_id": "e1", **fact, "unit": "percent_already_multiplied"}
    validation = validate_and_render(_canonical_claim_envelope(claim), [], [evidence])

    assert not validation.valid
    assert validation.trace["reason"] == "binding_mismatch"


def test_canonical_claim_for_an_absent_period_fails_closed():
    evidence = _period_range_evidence()
    fact = next(f for f in evidence.facts if f["period"] == "2026-06")
    validation = validate_and_render(
        _canonical_claim_envelope({"evidence_id": "e1", **fact, "period": "2019-01"}), [], [evidence])

    assert not validation.valid
    assert validation.trace["reason"] == "binding_mismatch"


def test_partial_coverage_is_surfaced_even_when_claims_are_per_entity():
    """Case 06: the model narrates a ranking with per-entity canonical claims;
    the underlying dataset covers 4 of 12 TRI assets, so the partial-coverage
    caveat must still reach the reader."""
    result = _run(AnalyticsBreakdownAssetAction(DB), {
        "metric": "noi_mensual_activo", "fund": "TRI", "assets": None, "period": "2026-06",
        "period_end": None, "order_by": "value_desc", "limit": None}, "e1")
    facts = result.evidence.facts
    envelope = {
        "fragments": ([{"type": "text", "text": "Ranking: "}] +
                      [{"type": "canonical_metric_ref", "claim_id": f"c{i}"} for i in range(len(facts))]),
        "canonical_metric_claims": [{"claim_id": f"c{i}", "evidence_id": "e1", **fact}
                                    for i, fact in enumerate(facts)],
        "governed_dataset_claims": [],
    }
    validation = validate_and_render(envelope, [], [result.evidence], DB)

    assert validation.valid
    assert validation.content.startswith("Ojo: estos datos alcanzan a 4 de ")
    assert validation.trace["coverage_status"] == "partial"


def test_complete_coverage_adds_no_caveat():
    result = _run(AnalyticsBreakdownAssetAction(DB), {
        "metric": "noi_mensual_activo", "fund": "TRI",
        "assets": ["INMOSA", "Viña Centro", "Mall Curicó"], "period": "2026-06",
        "period_end": None, "order_by": "value_desc", "limit": None}, "e1")
    fact = result.evidence.facts[0]
    validation = validate_and_render(_canonical_claim_envelope({"evidence_id": "e1", **fact}), [], [result.evidence])

    assert validation.valid
    assert not validation.content.startswith("Cobertura parcial")


def test_canonical_claim_against_an_unknown_evidence_id_fails_closed():
    evidence = _period_range_evidence()
    fact = evidence.facts[0]
    validation = validate_and_render(
        _canonical_claim_envelope({"evidence_id": "inventado", **fact}), [], [evidence])
    assert not validation.valid
    assert validation.trace["reason"] == "binding_mismatch"


def test_tool_payload_exposes_the_evidence_id_the_model_must_cite():
    result = _run(AnalyticsLookupAssetAction(DB), {
        "metric": "ltv_activo", "assets": ["Apo3001"], "period": "2026-06", "period_end": None}, "call_xyz")
    assert json.loads(result.content)["evidence_id"] == "call_xyz"
    assert result.evidence.evidence_id == "call_xyz"
    listed = _run(ListAssetsAction(DB), {"fund": "TRI", "period": None}, "call_abc")
    assert json.loads(listed.content)["evidence_id"] == "call_abc"
