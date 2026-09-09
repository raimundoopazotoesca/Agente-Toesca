"""A3.2c: transport of controlled_sql evidence to synthesis as noncanonical
supporting evidence.

Design frozen by the approved A3.2c authorization:
  1. supporting_evidence_claims is EXCLUSIVE to evidence_class="controlled_sql".
  2. canonical_metric / governed_dataset / verified_query keep their existing
     binding paths untouched -- they never go through supporting_evidence_claims.
  3. controlled_sql: citeable as supporting/noncanonical evidence; can never
     enter canonical_metric_claims, governed_dataset_claims or
     derived_metric_claims; never gains canonical authority by being cited.
  4. verified_query keeps structural support in the contract; no new
     producer/template, no fabricated verified_query_id/version.
  5. No second evidence/citation system -- this extends synthesis_schema.py,
     evidence_inventory.py and coverage_guard.py, the existing ones.
"""
from __future__ import annotations

from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.evidence_inventory import render_evidence_inventory
from tools.analyst_runtime.synthesis_schema import SYNTHESIS_ENVELOPE_SCHEMA

from tests.analyst_runtime._evidence_factory import mk_evidence

CANONICAL_FACT = {"metric_key": "vacancia_pct_fondo", "value": 5.94, "unit": "%",
                   "entity_id": "TRI", "period": "2026-06", "space_type": None,
                   "space_types": None, "measurement_unit": None}
CANONICAL_EVIDENCE = mk_evidence("e_canon", "canonical_metric", facts=(CANONICAL_FACT,))

GOVERNED_FACT = {"entity_id": "Apo4501", "period": "2026-06", "metric_key": None, "value": None}
GOVERNED_EVIDENCE = mk_evidence("e_gov", "governed_dataset", facts=(GOVERNED_FACT,),
                                 coverage={"status": "complete", "eligible_count": 1,
                                           "observed_count": 1, "universe_kind": "fund_assets"})

SQL_EVIDENCE = mk_evidence("e_sql", "controlled_sql", tool_name="run_sql")


def _envelope(**overrides):
    base = {"fragments": [], "canonical_metric_claims": [], "governed_dataset_claims": [],
            "derived_metric_claims": [], "table_claims": [], "supporting_evidence_claims": []}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Schema: supporting_evidence_claims + evidence_ref fragment exist and are
#    structurally isolated from the canonical/governed/derived claim types.
# ---------------------------------------------------------------------------

def test_schema_declares_supporting_evidence_claims_as_required_key():
    assert "supporting_evidence_claims" in SYNTHESIS_ENVELOPE_SCHEMA["required"]
    assert "supporting_evidence_claims" in SYNTHESIS_ENVELOPE_SCHEMA["properties"]


def test_schema_supporting_claim_shape_has_no_value_field():
    spec = SYNTHESIS_ENVELOPE_SCHEMA["properties"]["supporting_evidence_claims"]["items"]
    assert set(spec["required"]) == {"claim_id", "evidence_id"}
    assert "value" not in spec["properties"]
    assert "metric_key" not in spec["properties"]


def test_schema_fragments_accept_evidence_ref_type():
    fragment_types = {
        option["properties"]["type"]["const"]
        for option in SYNTHESIS_ENVELOPE_SCHEMA["properties"]["fragments"]["items"]["anyOf"]
    }
    assert "evidence_ref" in fragment_types


def test_schema_canonical_and_governed_claim_shapes_are_unchanged():
    canonical_required = set(SYNTHESIS_ENVELOPE_SCHEMA["properties"]["canonical_metric_claims"]["items"]["required"])
    governed_required = set(SYNTHESIS_ENVELOPE_SCHEMA["properties"]["governed_dataset_claims"]["items"]["required"])
    assert canonical_required == {"claim_id", "evidence_id", "metric_key", "value", "unit",
                                    "entity_id", "period", "space_type", "space_types", "measurement_unit"}
    assert governed_required == {"claim_id", "evidence_id", "metric_key", "entity_ids", "period", "universe_kind"}


# ---------------------------------------------------------------------------
# 2. Inventory: controlled_sql now exposed as supporting/noncanonical, in a
#    section distinct from the citeable canonical/governed/verified_query one.
# ---------------------------------------------------------------------------

def test_inventory_exposes_controlled_sql_as_supporting_evidence():
    rendered = render_evidence_inventory([SQL_EVIDENCE])
    assert rendered != ""
    assert "e_sql" in rendered
    assert "controlled_sql" in rendered


def test_inventory_never_places_controlled_sql_in_the_citeable_section():
    rendered = render_evidence_inventory([SQL_EVIDENCE, CANONICAL_EVIDENCE])
    lines = rendered.split("\n")
    citeable_lines = [line for line in lines if line.startswith("- evidence_id=e_canon")]
    supporting_lines = [line for line in lines if line.startswith("- evidence_id=e_sql")]
    assert len(citeable_lines) == 1
    assert len(supporting_lines) == 1
    # The two must not share one rendered line / header block.
    assert citeable_lines[0] != supporting_lines[0]


def test_inventory_supporting_section_carries_no_fact_values():
    rendered = render_evidence_inventory([SQL_EVIDENCE])
    # controlled_sql evidence built via mk_evidence has facts=() -- nothing
    # numeric should ever be synthesized into the inventory line for it.
    assert "value=" not in rendered


def test_inventory_with_only_canonical_and_governed_is_unchanged_shape():
    # Pre-existing behavior for the citeable classes must survive verbatim.
    rendered = render_evidence_inventory([CANONICAL_EVIDENCE, GOVERNED_EVIDENCE])
    assert "e_canon" in rendered
    assert "e_gov" in rendered
    assert "controlled_sql" not in rendered


def test_inventory_empty_when_no_evidence_at_all():
    assert render_evidence_inventory([]) == ""


# ---------------------------------------------------------------------------
# 3. Guard: supporting_evidence_claims binds only controlled_sql evidence_id.
# ---------------------------------------------------------------------------

def test_supporting_claim_binds_to_real_controlled_sql_evidence():
    envelope = _envelope(
        fragments=[{"type": "text", "text": "Se revisó una consulta de apoyo."},
                   {"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_sql"}],
    )
    result = validate_and_render(envelope, [], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is True


def test_supporting_claim_with_nonexistent_evidence_id_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "does_not_exist"}],
    )
    result = validate_and_render(envelope, [], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False


def test_supporting_claim_referencing_canonical_metric_evidence_id_fails_closed():
    # e_canon exists (as canonical_metric evidence), but supporting_evidence_claims
    # is exclusive to controlled_sql -- must not resolve just because the id exists.
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_canon"}],
    )
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False


def test_supporting_claim_referencing_governed_dataset_evidence_id_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_gov"}],
    )
    result = validate_and_render(envelope, [], [GOVERNED_EVIDENCE], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False


def test_omitting_supporting_evidence_claims_key_defaults_to_empty_and_still_validates():
    # Backward compatibility: an envelope with no supporting_evidence_claims
    # key at all (pre-A3.2c shape) must still validate exactly as before.
    envelope = {"fragments": [{"type": "canonical_metric_ref", "claim_id": "c1"}],
                "canonical_metric_claims": [{"claim_id": "c1", "evidence_id": "e_canon", **CANONICAL_FACT}],
                "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": []}
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [])
    assert result.valid is True


# ---------------------------------------------------------------------------
# 4. Cross-binding rejection: controlled_sql must never enter canonical/
#    governed/derived claim types, even when a well-formed claim tries.
# ---------------------------------------------------------------------------

def test_controlled_sql_evidence_id_cannot_enter_canonical_metric_claims():
    envelope = _envelope(
        fragments=[{"type": "canonical_metric_ref", "claim_id": "c1"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": "e_sql", **CANONICAL_FACT}],
    )
    result = validate_and_render(envelope, [SQL_EVIDENCE], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False


def test_controlled_sql_evidence_id_cannot_enter_governed_dataset_claims():
    envelope = _envelope(
        fragments=[{"type": "governed_dataset_ref", "claim_id": "g1"}],
        governed_dataset_claims=[{"claim_id": "g1", "evidence_id": "e_sql", "metric_key": None,
                                   "entity_ids": ["Apo4501"], "period": "2026-06", "universe_kind": "fund_assets"}],
    )
    result = validate_and_render(envelope, [], [SQL_EVIDENCE], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False


def test_supporting_claim_id_cannot_be_used_as_derived_operand():
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"},
                   {"type": "derived_metric_ref", "claim_id": "d1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_sql"}],
        derived_metric_claims=[{"claim_id": "d1", "operation": "difference",
                                 "lhs_claim_id": "s1", "rhs_claim_id": "s1"}],
    )
    result = validate_and_render(envelope, [], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False


def test_supporting_claim_id_colliding_with_canonical_claim_id_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "canonical_metric_ref", "claim_id": "c1"},
                   {"type": "evidence_ref", "claim_id": "c1"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": "e_canon", **CANONICAL_FACT}],
        supporting_evidence_claims=[{"claim_id": "c1", "evidence_id": "e_sql"}],
    )
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False


# ---------------------------------------------------------------------------
# 5. Error / no-evidence semantics untouched by this change.
# ---------------------------------------------------------------------------

def test_no_supporting_evidence_available_still_fails_closed_on_a_supporting_claim():
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_sql"}],
    )
    result = validate_and_render(envelope, [], [])  # no supporting_evidence passed at all
    assert result.valid is False


def test_canonical_only_answer_with_empty_supporting_claims_still_passes():
    envelope = _envelope(
        fragments=[{"type": "canonical_metric_ref", "claim_id": "c1"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": "e_canon", **CANONICAL_FACT}],
    )
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is True
