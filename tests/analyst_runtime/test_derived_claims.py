"""Stage 5.4b: DerivedClaim arithmetic is deterministic and never runs on
display strings; unbound computed literals in free text fail closed."""
from __future__ import annotations

import pytest

from tests.analyst_runtime._evidence_factory import mk_evidence
from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.derived_claims import DerivedClaimError, compute_derived_claim

NOI_PT_2025 = mk_evidence("e2025", "canonical_metric",
    facts=({"metric_key": "noi_anual", "value": 172868.0, "unit": "UF", "entity_id": "PT", "period": "2025"},))
NOI_PT_2024 = mk_evidence("e2024", "canonical_metric",
    facts=({"metric_key": "noi_anual", "value": 164612.0, "unit": "UF", "entity_id": "PT", "period": "2024"},))
NOI_TRI_2025 = mk_evidence("e_tri", "canonical_metric",
    facts=({"metric_key": "noi_anual", "value": 315312.0, "unit": "UF", "entity_id": "TRI", "period": "2025"},))
LTV_PT = mk_evidence("e_ltv_pt", "canonical_metric",
    facts=({"metric_key": "ltv", "value": 81.22, "unit": "pct_0_100", "entity_id": "PT", "period": "2025"},))
LTV_TRI = mk_evidence("e_ltv_tri", "canonical_metric",
    facts=({"metric_key": "ltv", "value": 61.02, "unit": "pct_0_100", "entity_id": "TRI", "period": "2025"},))

CANONICAL_2Y = [NOI_PT_2025, NOI_PT_2024]


def _claims(*items):
    return [{"claim_id": ev.evidence_id.replace("e", "c"), "evidence_id": ev.evidence_id,
             **{k: v for k, v in ev.facts[0].items()}} for ev in items]


def test_locale_trap_difference_is_raw_arithmetic_not_display_string_math():
    """The bug report's exact trap: 172.868 / 164.612 are THOUSANDS-separated
    display strings. The difference of the raw values (172868 - 164612) must
    be 8256 UF -> "8.256 UF", never "8,26 UF" (which is what you get if you
    subtract the display strings as decimals: 172.868 - 164.612 = 8.256)."""
    claims = _claims(NOI_PT_2025, NOI_PT_2024)
    envelope = {
        "fragments": [{"type": "derived_metric_ref", "claim_id": "d1"}],
        "canonical_metric_claims": claims,
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "difference", "lhs_claim_id": "c2025", "rhs_claim_id": "c2024"}],
    }
    result = validate_and_render(envelope, CANONICAL_2Y, [])
    assert result.valid
    assert result.content == "8.256 UF"
    assert result.content != "8,26 UF"


def test_percent_change_is_derived_deterministically():
    claims = _claims(NOI_PT_2025, NOI_PT_2024)
    envelope = {
        "fragments": [{"type": "derived_metric_ref", "claim_id": "d1"}],
        "canonical_metric_claims": claims,
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "percent_change", "lhs_claim_id": "c2024", "rhs_claim_id": "c2025"}],
    }
    result = validate_and_render(envelope, CANONICAL_2Y, [])
    assert result.valid and result.content == "5,0%"


def test_difference_between_two_funds():
    claims = _claims(NOI_TRI_2025, NOI_PT_2025)
    envelope = {
        "fragments": [{"type": "derived_metric_ref", "claim_id": "d1"}],
        "canonical_metric_claims": claims,
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "difference", "lhs_claim_id": "c_tri", "rhs_claim_id": "c2025"}],
    }
    result = validate_and_render(envelope, [NOI_TRI_2025, NOI_PT_2025], [])
    assert result.valid and result.content == "142.444 UF"


def test_percentage_point_difference():
    claims = _claims(LTV_PT, LTV_TRI)
    envelope = {
        "fragments": [{"type": "derived_metric_ref", "claim_id": "d1"}],
        "canonical_metric_claims": claims,
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "percentage_point_difference", "lhs_claim_id": "c_ltv_pt", "rhs_claim_id": "c_ltv_tri"}],
    }
    result = validate_and_render(envelope, [LTV_PT, LTV_TRI], [])
    assert result.valid and result.content == "20,20 pp"


def test_unbound_derived_quantity_in_free_text_fails_closed():
    """A computed number written directly in a text fragment (bypassing
    derived_metric_ref entirely) must be rejected, not passed through because
    it happens to be numerically plausible."""
    claims = _claims(NOI_PT_2025, NOI_PT_2024)
    envelope = {
        "fragments": [{"type": "text", "text": "un alza aproximada de 5,0% (cerca de 8,26 UF)"}],
        "canonical_metric_claims": claims,
        "governed_dataset_claims": [],
        "derived_metric_claims": [],
    }
    result = validate_and_render(envelope, CANONICAL_2Y, [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_derived_quantity"


def test_plain_integer_years_in_prose_are_still_permitted():
    """The guard must not collaterally ban ordinary integers (years, counts)
    that carry no decimal separator or percent sign."""
    claims = _claims(NOI_PT_2025)
    envelope = {
        "fragments": [{"type": "text", "text": "En el periodo 2025 el fondo reporto lo siguiente: "},
                      {"type": "canonical_metric_ref", "claim_id": "c2025"}],
        "canonical_metric_claims": claims,
        "governed_dataset_claims": [],
        "derived_metric_claims": [],
    }
    result = validate_and_render(envelope, [NOI_PT_2025], [])
    assert result.valid


def test_derived_claim_referencing_unbound_operand_fails_closed():
    claims = _claims(NOI_PT_2025)
    envelope = {
        "fragments": [{"type": "derived_metric_ref", "claim_id": "d1"}],
        "canonical_metric_claims": claims,
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "difference", "lhs_claim_id": "c2025", "rhs_claim_id": "does_not_exist"}],
    }
    result = validate_and_render(envelope, [NOI_PT_2025], [])
    assert not result.valid


def test_derived_claim_operand_unit_mismatch_fails_closed():
    lhs = mk_evidence("e_a", "canonical_metric", facts=({"metric_key": "noi_anual", "value": 100.0, "unit": "UF", "entity_id": "PT", "period": "2025"},))
    rhs = mk_evidence("e_b", "canonical_metric", facts=({"metric_key": "gastos", "value": 50.0, "unit": "clp", "entity_id": "PT", "period": "2025"},))
    with pytest.raises(DerivedClaimError):
        compute_derived_claim("d1", "difference", lhs.facts[0], rhs.facts[0], "a", "b")


def test_raw_values_untouched_by_display_formatting():
    """compute_derived_claim never rounds or reformats the operand values it
    reads -- the arithmetic happens on the exact raw floats."""
    claim = compute_derived_claim("d1", "difference", NOI_PT_2025.facts[0], NOI_PT_2024.facts[0], "c2025", "c2024")
    assert claim.value == 172868.0 - 164612.0 == 8256.0


def test_comparison_operation_greater():
    claim = compute_derived_claim("d1", "comparison", NOI_TRI_2025.facts[0], NOI_PT_2025.facts[0], "c_tri", "c2025")
    assert claim.value == 1.0
    assert claim.unit == "comparison"


def test_comparison_operation_lesser():
    claim = compute_derived_claim("d1", "comparison", NOI_PT_2025.facts[0], NOI_TRI_2025.facts[0], "c2025", "c_tri")
    assert claim.value == -1.0


def test_comparison_operation_equal():
    same = {"metric_key": "noi_anual", "value": 100.0, "unit": "UF", "entity_id": "PT", "period": "2025"}
    claim = compute_derived_claim("d1", "comparison", same, same, "a", "b")
    assert claim.value == 0.0


def test_comparison_operation_rejects_unit_mismatch():
    lhs = {"metric_key": "noi_anual", "value": 100.0, "unit": "UF", "entity_id": "PT", "period": "2025"}
    rhs = {"metric_key": "gastos", "value": 50.0, "unit": "clp", "entity_id": "PT", "period": "2025"}
    with pytest.raises(DerivedClaimError):
        compute_derived_claim("d1", "comparison", lhs, rhs, "a", "b")


def test_derived_claim_lineage_points_back_to_source_claim_ids():
    claim = compute_derived_claim("d1", "percent_change", NOI_PT_2024.facts[0], NOI_PT_2025.facts[0], "c2024", "c2025")
    assert claim.lineage["lhs_claim_id"] == "c2024"
    assert claim.lineage["rhs_claim_id"] == "c2025"
    assert claim.lineage["lhs_value"] == 164612.0
    assert claim.lineage["rhs_value"] == 172868.0
