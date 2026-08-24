import pytest

from tools.analyst_runtime.presentation import AllowedClaim, render_segments, validate_structured_output
from tools.analyst_runtime.session import _allowed_claims
from tools.analyst_runtime.transport import ToolEvidence


CLAIM = AllowedClaim("c1", "e1", "synthetic_flow", "fund-a", 1234.5, "UF", "2025-06", "sum")
SECOND_CLAIM = AllowedClaim("c2", "e2", "synthetic_flow", "fund-b", 55.0, "%", "2025-07", "avg")


def test_renderer_owns_the_business_value_string():
    assert render_segments({"segments": [{"type": "text", "text": "Resultado: "}, {"type": "claim_ref", "claim_id": "c1"}]}, (CLAIM,)) == "Resultado: 1.234 UF"


def test_renderer_uses_human_value_and_period_instead_of_debug_serialization():
    annual = AllowedClaim("c1", "e1", "noi_mensual_fondo", "PT", 82992.50599592587, "UF", "2025-01..2025-06", "sum")
    ratio = AllowedClaim("c2", "e2", "ltv_fondo", "TRI", 0.6102, "ratio_0_1", "2026-06")
    assert render_segments({"segments": [{"type": "claim_ref", "claim_id": "c1"}]}, (annual,)) == "82.993 UF"
    assert render_segments({"segments": [{"type": "claim_ref", "claim_id": "c2"}]}, (ratio,)) == "61,02%"


@pytest.mark.parametrize(("field", "value"), [
    ("value", 999.0), ("unit", "%"), ("entity_id", "fund-b"),
    ("period", "2024-01"), ("aggregation", "avg"),
])
def test_claim_construction_preserves_the_authoritative_semantics(field, value):
    values = {**CLAIM.__dict__, field: value}
    mutated = AllowedClaim(**values)
    assert getattr(mutated, field) == value
    assert getattr(mutated, field) == value


def test_unknown_claim_fails_closed():
    with pytest.raises(ValueError, match="unknown"):
        render_segments({"segments": [{"type": "claim_ref", "claim_id": "altered"}]}, (CLAIM,))


def test_malformed_output_fails_closed():
    with pytest.raises(ValueError, match="malformed"):
        validate_structured_output({"segments": [{"type": "claim_ref"}]}, (CLAIM,))


def test_free_prose_cannot_introduce_a_business_quantity():
    with pytest.raises(ValueError, match="business quantity"):
        validate_structured_output({"segments": [{"type": "text", "text": "sube 94,1%"}, {"type": "claim_ref", "claim_id": "c1"}]}, (CLAIM,))


def test_claim_omission_fails_closed():
    with pytest.raises(ValueError, match="omitted"):
        validate_structured_output({"segments": [{"type": "text", "text": "resultado"}]}, (CLAIM,))


def test_multiple_claims_must_each_be_rendered_once():
    assert validate_structured_output({"segments": [
        {"type": "text", "text": "primero "}, {"type": "claim_ref", "claim_id": "c1"},
        {"type": "text", "text": " y luego "}, {"type": "claim_ref", "claim_id": "c2"},
    ]}, (CLAIM, SECOND_CLAIM)) == "primero 1.234 UF y luego 55,00%"


def test_allowed_claims_preserve_aggregation_and_lineage_from_evidence():
    evidence = ToolEvidence("e1", "canonical_metric", semantic_contract={"aggregation": "sum"},
                            provenance={"source_periods": ["2025-01", "2025-02"]},
                            facts=({"metric_key": "synthetic_flow", "value": 1234.5, "unit": "UF",
                                    "entity_id": "fund-a", "period": "2025-01..2025-02"},))
    claims = _allowed_claims({"canonical_metric_claims": [{"claim_id": "c1", "evidence_id": "e1",
        "metric_key": "synthetic_flow", "value": 1234.5, "unit": "UF", "entity_id": "fund-a",
        "period": "2025-01..2025-02"}]}, [evidence])
    assert claims == (AllowedClaim("c1", "e1", "synthetic_flow", "fund-a", 1234.5, "UF",
                                   "2025-01..2025-02", "sum", {"source_periods": ["2025-01", "2025-02"]}),)


def test_free_prose_can_differ_while_fact_stays_deterministic():
    first = render_segments({"segments": [{"type": "text", "text": "A: "}, {"type": "claim_ref", "claim_id": "c1"}]}, (CLAIM,))
    second = render_segments({"segments": [{"type": "text", "text": "B: "}, {"type": "claim_ref", "claim_id": "c1"}]}, (CLAIM,))
    assert first.endswith("1.234 UF") and second.endswith("1.234 UF")
