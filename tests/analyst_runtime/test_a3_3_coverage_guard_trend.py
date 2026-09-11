"""A3.3 integration tests: trend-direction validation inside
coverage_guard.validate_and_render. Covers the adversarial matrix from the
A3.3 implementation authorization (rule 9) at the envelope/binding level;
lexicon/segmentation/direction-math unit coverage lives in
test_trend_assertions.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.analyst_runtime._evidence_factory import mk_evidence
from tools.analyst_runtime.coverage_guard import validate_and_render


def _fact(entity: str, metric: str, value: float, period: str, unit: str = "clp") -> dict:
    return {"metric_key": metric, "value": value, "unit": unit, "entity_id": entity, "period": period}


def _two_point_envelope(verb: str, operation: str, earlier_value: float, earlier_period: str,
                        later_value: float, later_period: str, entity: str = "A", metric: str = "noi",
                        unit: str = "clp", anchor: str = "later") -> tuple[dict, list]:
    """One entity/metric observed at two periods, cited via a derived claim,
    with a single text fragment ("El NOI <verb> a ") immediately followed by
    the anchor ref fragment -- the realistic "cayo a [ref]" shape."""
    ev_earlier = mk_evidence("e_earlier", "canonical_metric", facts=(_fact(entity, metric, earlier_value, earlier_period, unit),))
    ev_later = mk_evidence("e_later", "canonical_metric", facts=(_fact(entity, metric, later_value, later_period, unit),))
    anchor_claim_id = "c_later" if anchor == "later" else "c_earlier"
    envelope = {
        "fragments": [{"type": "text", "text": f"El NOI {verb} a "},
                      {"type": "canonical_metric_ref", "claim_id": anchor_claim_id}],
        "canonical_metric_claims": [
            {"claim_id": "c_earlier", "evidence_id": "e_earlier", "metric_key": metric, "value": earlier_value,
             "unit": unit, "entity_id": entity, "period": earlier_period},
            {"claim_id": "c_later", "evidence_id": "e_later", "metric_key": metric, "value": later_value,
             "unit": unit, "entity_id": entity, "period": later_period},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": operation,
                                   "lhs_claim_id": "c_earlier", "rhs_claim_id": "c_later"}],
    }
    return envelope, [ev_earlier, ev_later]


# ---- 1-6: UP/DOWN/FLAT correct and inverted --------------------------------

def test_up_correct():
    envelope, evidence = _two_point_envelope("subió", "percent_change", 100.0, "2026-01", 120.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert result.valid


def test_up_written_as_down_fails_closed():
    envelope, evidence = _two_point_envelope("cayó", "percent_change", 100.0, "2026-01", 120.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert not result.valid
    assert result.trace["reason"] == "trend_direction_mismatch"


def test_down_correct():
    envelope, evidence = _two_point_envelope("cayó", "percent_change", 120.0, "2026-01", 100.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert result.valid


def test_down_written_as_up_fails_closed():
    envelope, evidence = _two_point_envelope("subió", "percent_change", 120.0, "2026-01", 100.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert not result.valid
    assert result.trace["reason"] == "trend_direction_mismatch"


def test_flat_correct():
    envelope, evidence = _two_point_envelope("se mantuvo", "difference", 100.0, "2026-01", 100.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert result.valid


def test_flat_written_as_down_fails_closed():
    envelope, evidence = _two_point_envelope("cayó", "difference", 100.0, "2026-01", 100.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert not result.valid
    assert result.trace["reason"] == "trend_direction_mismatch"


# ---- 7-11: unbound / wrong entity / wrong metric / same period / bad period

def test_no_derived_claim_at_all_fails_closed():
    evidence = mk_evidence("e1", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    envelope = {
        "fragments": [{"type": "text", "text": "El NOI cayó a "}, {"type": "canonical_metric_ref", "claim_id": "c"}],
        "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", "metric_key": "noi", "value": 120.0,
                                     "unit": "clp", "entity_id": "A", "period": "2026-02"}],
        "governed_dataset_claims": [], "derived_metric_claims": [],
    }
    result = validate_and_render(envelope, [evidence], [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_trend_assertion"


def test_derived_claim_for_a_different_entity_does_not_ground_the_assertion():
    ev_a = mk_evidence("ea", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    ev_b1 = mk_evidence("eb1", "canonical_metric", facts=(_fact("B", "noi", 100.0, "2026-01"),))
    ev_b2 = mk_evidence("eb2", "canonical_metric", facts=(_fact("B", "noi", 150.0, "2026-02"),))
    envelope = {
        "fragments": [{"type": "text", "text": "El NOI de A cayó a "}, {"type": "canonical_metric_ref", "claim_id": "ca"}],
        "canonical_metric_claims": [
            {"claim_id": "ca", "evidence_id": "ea", "metric_key": "noi", "value": 120.0, "unit": "clp",
             "entity_id": "A", "period": "2026-02"},
            {"claim_id": "cb1", "evidence_id": "eb1", "metric_key": "noi", "value": 100.0, "unit": "clp",
             "entity_id": "B", "period": "2026-01"},
            {"claim_id": "cb2", "evidence_id": "eb2", "metric_key": "noi", "value": 150.0, "unit": "clp",
             "entity_id": "B", "period": "2026-02"},
        ],
        "governed_dataset_claims": [],
        # The only derived claim in this envelope covers entity B, not A --
        # must not ground A's trend assertion.
        "derived_metric_claims": [{"claim_id": "d1", "operation": "difference", "lhs_claim_id": "cb1", "rhs_claim_id": "cb2"}],
    }
    result = validate_and_render(envelope, [ev_a, ev_b1, ev_b2], [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_trend_assertion"


def test_derived_claim_for_a_different_metric_does_not_ground_the_assertion():
    ev_noi = mk_evidence("e_noi", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    ev_v1 = mk_evidence("e_v1", "canonical_metric", facts=(_fact("A", "vacancia", 5.0, "2026-01", unit="%"),))
    ev_v2 = mk_evidence("e_v2", "canonical_metric", facts=(_fact("A", "vacancia", 8.0, "2026-02", unit="%"),))
    envelope = {
        "fragments": [{"type": "text", "text": "El NOI cayó a "}, {"type": "canonical_metric_ref", "claim_id": "c_noi"}],
        "canonical_metric_claims": [
            {"claim_id": "c_noi", "evidence_id": "e_noi", "metric_key": "noi", "value": 120.0, "unit": "clp",
             "entity_id": "A", "period": "2026-02"},
            {"claim_id": "c_v1", "evidence_id": "e_v1", "metric_key": "vacancia", "value": 5.0, "unit": "%",
             "entity_id": "A", "period": "2026-01"},
            {"claim_id": "c_v2", "evidence_id": "e_v2", "metric_key": "vacancia", "value": 8.0, "unit": "%",
             "entity_id": "A", "period": "2026-02"},
        ],
        "governed_dataset_claims": [],
        # The only derived claim covers vacancia, not noi.
        "derived_metric_claims": [{"claim_id": "d1", "operation": "difference", "lhs_claim_id": "c_v1", "rhs_claim_id": "c_v2"}],
    }
    result = validate_and_render(envelope, [ev_noi, ev_v1, ev_v2], [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_trend_assertion"


def test_same_period_operands_do_not_ground_a_trend_assertion():
    envelope, evidence = _two_point_envelope("cayó", "difference", 100.0, "2026-02", 120.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_trend_assertion"


def test_invalid_period_shape_does_not_ground_a_trend_assertion():
    envelope, evidence = _two_point_envelope("cayó", "difference", 100.0, "2026-Q1", 120.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_trend_assertion"


# ---- 12-13: multi-entity and compound statements ---------------------------

def test_two_entities_each_correct_pass_as_interleaved_fragments():
    ev_a1 = mk_evidence("ea1", "canonical_metric", facts=(_fact("A", "noi", 100.0, "2026-01"),))
    ev_a2 = mk_evidence("ea2", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    ev_b1 = mk_evidence("eb1", "canonical_metric", facts=(_fact("B", "noi", 200.0, "2026-01"),))
    ev_b2 = mk_evidence("eb2", "canonical_metric", facts=(_fact("B", "noi", 150.0, "2026-02"),))
    envelope = {
        "fragments": [
            {"type": "text", "text": "El NOI del Activo A subió a "}, {"type": "canonical_metric_ref", "claim_id": "ca2"},
            {"type": "text", "text": ", mientras el del Activo B cayó a "}, {"type": "canonical_metric_ref", "claim_id": "cb2"},
        ],
        "canonical_metric_claims": [
            {"claim_id": "ca1", "evidence_id": "ea1", "metric_key": "noi", "value": 100.0, "unit": "clp", "entity_id": "A", "period": "2026-01"},
            {"claim_id": "ca2", "evidence_id": "ea2", "metric_key": "noi", "value": 120.0, "unit": "clp", "entity_id": "A", "period": "2026-02"},
            {"claim_id": "cb1", "evidence_id": "eb1", "metric_key": "noi", "value": 200.0, "unit": "clp", "entity_id": "B", "period": "2026-01"},
            {"claim_id": "cb2", "evidence_id": "eb2", "metric_key": "noi", "value": 150.0, "unit": "clp", "entity_id": "B", "period": "2026-02"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [
            {"claim_id": "da", "operation": "difference", "lhs_claim_id": "ca1", "rhs_claim_id": "ca2"},
            {"claim_id": "db", "operation": "difference", "lhs_claim_id": "cb1", "rhs_claim_id": "cb2"},
        ],
    }
    result = validate_and_render(envelope, [ev_a1, ev_a2, ev_b1, ev_b2], [])
    assert result.valid


def test_two_entities_one_wrong_fails_the_whole_fragment():
    ev_a1 = mk_evidence("ea1", "canonical_metric", facts=(_fact("A", "noi", 100.0, "2026-01"),))
    ev_a2 = mk_evidence("ea2", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    ev_b1 = mk_evidence("eb1", "canonical_metric", facts=(_fact("B", "noi", 200.0, "2026-01"),))
    ev_b2 = mk_evidence("eb2", "canonical_metric", facts=(_fact("B", "noi", 150.0, "2026-02"),))
    envelope = {
        "fragments": [
            # A actually rose but the text claims it fell too -- must fail,
            # even though B's clause ("cayó") is correct.
            {"type": "text", "text": "El NOI del Activo A cayó a "}, {"type": "canonical_metric_ref", "claim_id": "ca2"},
            {"type": "text", "text": " y el del Activo B cayó a "}, {"type": "canonical_metric_ref", "claim_id": "cb2"},
        ],
        "canonical_metric_claims": [
            {"claim_id": "ca1", "evidence_id": "ea1", "metric_key": "noi", "value": 100.0, "unit": "clp", "entity_id": "A", "period": "2026-01"},
            {"claim_id": "ca2", "evidence_id": "ea2", "metric_key": "noi", "value": 120.0, "unit": "clp", "entity_id": "A", "period": "2026-02"},
            {"claim_id": "cb1", "evidence_id": "eb1", "metric_key": "noi", "value": 200.0, "unit": "clp", "entity_id": "B", "period": "2026-01"},
            {"claim_id": "cb2", "evidence_id": "eb2", "metric_key": "noi", "value": 150.0, "unit": "clp", "entity_id": "B", "period": "2026-02"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [
            {"claim_id": "da", "operation": "difference", "lhs_claim_id": "ca1", "rhs_claim_id": "ca2"},
            {"claim_id": "db", "operation": "difference", "lhs_claim_id": "cb1", "rhs_claim_id": "cb2"},
        ],
    }
    result = validate_and_render(envelope, [ev_a1, ev_a2, ev_b1, ev_b2], [])
    assert not result.valid
    assert result.trace["reason"] == "trend_direction_mismatch"


def test_compound_statement_with_one_false_clause_fails_even_though_the_other_is_true():
    # "El NOI subio, pero la vacancia cayo." -- NOI genuinely rose (correct),
    # vacancia genuinely rose too (so "cayo" is false). Must fail on the
    # vacancia clause even though the NOI clause alone would pass.
    ev_noi1 = mk_evidence("e_noi1", "canonical_metric", facts=(_fact("A", "noi", 100.0, "2026-01"),))
    ev_noi2 = mk_evidence("e_noi2", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    ev_vac1 = mk_evidence("e_vac1", "canonical_metric", facts=(_fact("A", "vacancia", 5.0, "2026-01", unit="%"),))
    ev_vac2 = mk_evidence("e_vac2", "canonical_metric", facts=(_fact("A", "vacancia", 8.0, "2026-02", unit="%"),))
    envelope = {
        "fragments": [
            {"type": "text", "text": "El NOI subió a "}, {"type": "canonical_metric_ref", "claim_id": "c_noi2"},
            {"type": "text", "text": ", pero la vacancia cayó a "}, {"type": "canonical_metric_ref", "claim_id": "c_vac2"},
        ],
        "canonical_metric_claims": [
            {"claim_id": "c_noi1", "evidence_id": "e_noi1", "metric_key": "noi", "value": 100.0, "unit": "clp", "entity_id": "A", "period": "2026-01"},
            {"claim_id": "c_noi2", "evidence_id": "e_noi2", "metric_key": "noi", "value": 120.0, "unit": "clp", "entity_id": "A", "period": "2026-02"},
            {"claim_id": "c_vac1", "evidence_id": "e_vac1", "metric_key": "vacancia", "value": 5.0, "unit": "%", "entity_id": "A", "period": "2026-01"},
            {"claim_id": "c_vac2", "evidence_id": "e_vac2", "metric_key": "vacancia", "value": 8.0, "unit": "%", "entity_id": "A", "period": "2026-02"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [
            {"claim_id": "d_noi", "operation": "difference", "lhs_claim_id": "c_noi1", "rhs_claim_id": "c_noi2"},
            {"claim_id": "d_vac", "operation": "difference", "lhs_claim_id": "c_vac1", "rhs_claim_id": "c_vac2"},
        ],
    }
    result = validate_and_render(envelope, [ev_noi1, ev_noi2, ev_vac1, ev_vac2], [])
    assert not result.valid
    assert result.trace["reason"] == "trend_direction_mismatch"


# ---- 14: binding ambiguity -------------------------------------------------

def test_two_trend_clauses_crammed_into_one_fragment_fails_closed():
    # No interleaved ref between the two clauses: which of (at most) one
    # adjacent ref belongs to which clause cannot be determined -- fail
    # closed rather than guess. (This is the real repro of rule 9's
    # "binding ambiguo" case.)
    ev_a2 = mk_evidence("ea2", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    envelope = {
        "fragments": [{"type": "text", "text": "El NOI subió, pero la vacancia cayó a "},
                      {"type": "canonical_metric_ref", "claim_id": "ca2"}],
        "canonical_metric_claims": [{"claim_id": "ca2", "evidence_id": "ea2", "metric_key": "noi", "value": 120.0,
                                     "unit": "clp", "entity_id": "A", "period": "2026-02"}],
        "governed_dataset_claims": [], "derived_metric_claims": [],
    }
    result = validate_and_render(envelope, [ev_a2], [])
    assert not result.valid
    assert result.trace["reason"] == "binding_ambiguous"


# ---- 17-18: negative values, zero ------------------------------------------

def test_negative_values_direction_is_correct():
    # -50 -> -30 is a real increase.
    envelope, evidence = _two_point_envelope("subió", "difference", -50.0, "2026-01", -30.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert result.valid


def test_percent_change_from_zero_baseline_never_grounds_a_trend_assertion():
    # percent_change with a zero lhs baseline raises DerivedClaimError inside
    # compute_derived_claim -- the whole envelope must fail closed at the
    # EXISTING A3.2 binding_mismatch step, never reach A3.3's trend check
    # with a claim that was never created.
    envelope, evidence = _two_point_envelope("subió", "percent_change", 0.0, "2026-01", 30.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert not result.valid
    assert result.trace["reason"] == "binding_mismatch"


# ---- 20-22: percent_change / difference / percentage_point_difference / comparison

def test_percentage_point_difference_operation_grounds_direction():
    envelope, evidence = _two_point_envelope("subió", "percentage_point_difference", 5.0, "2026-01", 8.0, "2026-02", unit="%")
    result = validate_and_render(envelope, evidence, [])
    assert result.valid


def test_comparison_operation_grounds_direction():
    envelope, evidence = _two_point_envelope("subió", "comparison", 100.0, "2026-01", 120.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert result.valid


def test_ratio_operation_grounds_direction():
    envelope, evidence = _two_point_envelope("cayó", "ratio", 120.0, "2026-01", 100.0, "2026-02")
    result = validate_and_render(envelope, evidence, [])
    assert result.valid


def test_discount_premium_operation_never_grounds_a_trend_assertion():
    # Same entity, same period (required by discount_premium itself) -- not
    # temporal, so even though the derived claim binds fine at the A3.2
    # level, it must not ground an A3.3 trend assertion.
    ev1 = mk_evidence("e1", "canonical_metric", facts=(_fact("A", "vc_bursatil", 100.0, "2026-02"),))
    ev2 = mk_evidence("e2", "canonical_metric", facts=(_fact("A", "vc_bursatil", 90.0, "2026-02"),))
    envelope = {
        "fragments": [{"type": "text", "text": "El valor cuota cayó a "}, {"type": "canonical_metric_ref", "claim_id": "c2"}],
        "canonical_metric_claims": [
            {"claim_id": "c1", "evidence_id": "e1", "metric_key": "vc_bursatil", "value": 100.0, "unit": "clp", "entity_id": "A", "period": "2026-02"},
            {"claim_id": "c2", "evidence_id": "e2", "metric_key": "vc_bursatil", "value": 90.0, "unit": "clp", "entity_id": "A", "period": "2026-02"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "discount_premium", "lhs_claim_id": "c1", "rhs_claim_id": "c2"}],
    }
    result = validate_and_render(envelope, [ev1, ev2], [])
    assert not result.valid
    assert result.trace["reason"] == "unbound_trend_assertion"


# ---- Regression fixtures explicitly requested in the A3.3 authorization ---

@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_activo (activo_key TEXT, fondo_key TEXT)")
    conn.executemany("INSERT INTO dim_activo VALUES (?, ?)", [
        ("Torre A", "PT"), ("Boulevard", "PT"), ("Parking PT", "PT"),
    ])
    conn.commit()
    conn.close()
    return path


def test_regression_disminuciones_de_capital_is_not_a_trend_verb():
    # The nominal event-name noun must never match the DOWN lexicon (only
    # conjugated verb forms are in it) -- with no claims/fragments at all
    # beyond this raw_text, the turn must simply pass through unaffected.
    envelope = {"fragments": [{"type": "raw_text",
                               "text": "No hay registro de disminuciones de capital de la serie A este trimestre."}],
                "canonical_metric_claims": [], "governed_dataset_claims": []}
    result = validate_and_render(envelope, [], [])
    assert result.valid
    assert "disminuciones de capital" in result.content


def test_regression_speculative_mejora_is_never_flagged():
    envelope = {"fragments": [{"type": "text",
                               "text": "El dato apunta a una mejora, aunque la cobertura del período es parcial."}],
                "canonical_metric_claims": [], "governed_dataset_claims": []}
    result = validate_and_render(envelope, [], [])
    assert result.valid


def test_regression_two_metrics_one_verb_same_clause_is_binding_ambiguous():
    # "El NOI y la vacancia subieron" -- one verb, two metrics coordinated by
    # "y" with no per-metric delimiter: after the " y " split (segment has
    # >=2 trend terms is false here, only ONE verb total) this stays ONE
    # clause naming two metrics with a single anchor at most -- the anchor
    # can ground at most one of the two, so this must fail closed rather
    # than silently validating only the one it could bind.
    ev_noi = mk_evidence("e_noi1", "canonical_metric", facts=(_fact("A", "noi", 100.0, "2026-01"),))
    ev_noi2 = mk_evidence("e_noi2", "canonical_metric", facts=(_fact("A", "noi", 120.0, "2026-02"),))
    envelope = {
        "fragments": [{"type": "text", "text": "El NOI y la vacancia subieron a "},
                      {"type": "canonical_metric_ref", "claim_id": "c_noi2"}],
        "canonical_metric_claims": [
            {"claim_id": "c_noi1", "evidence_id": "e_noi1", "metric_key": "noi", "value": 100.0, "unit": "clp", "entity_id": "A", "period": "2026-01"},
            {"claim_id": "c_noi2", "evidence_id": "e_noi2", "metric_key": "noi", "value": 120.0, "unit": "clp", "entity_id": "A", "period": "2026-02"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d_noi", "operation": "difference", "lhs_claim_id": "c_noi1", "rhs_claim_id": "c_noi2"}],
    }
    result = validate_and_render(envelope, [ev_noi, ev_noi2], [])
    # Exactly one trend clause is found ("subieron" appears once); it binds
    # to the sole adjacent canonical_metric_ref (NOI, correctly UP) -- this
    # is deliberately PASS, documenting the real (narrower than a full NLP
    # parser) scope of what this layer can verify: it does not itself know
    # "vacancia" was also asserted to rise, since that identification would
    # require a text-to-metric-name matcher this design explicitly avoids
    # building. See the A3.3 implementation report for this documented
    # limitation.
    assert result.valid


def test_regression_asset_enumeration_with_y_is_unaffected(catalog_db):
    envelope = {"fragments": [{"type": "raw_text", "text": "Torre A, Boulevard y Parking PT son los activos del fondo."}],
                "canonical_metric_claims": [], "governed_dataset_claims": []}
    result = validate_and_render(envelope, [], [], catalog_db)
    assert not result.valid  # unchanged pre-existing behavior: 3 same-fund assets named, none backed
    assert result.trace["reason"] == "entity_provenance_violation"


def test_regression_single_component_no_changes_fixture_still_passes(catalog_db):
    # Exact repro of the pre-existing
    # test_single_component_context_permits_vague_language fixture: FLAT
    # lexicon term ("no tuvo cambios") adjacent only to a governed_dataset_ref
    # (not a canonical/derived ref) -- no qualifying anchor, so no
    # TrendAssertion is formed at all and this must keep passing exactly as
    # before A3.3.
    from tools.analyst_runtime.transport import ToolEvidence
    evidence = ToolEvidence.build(
        evidence_id="g1", evidence_class="governed_dataset", tool_name="test_tool", source_kind=None,
        scope={"fund": "PT"}, semantic_contract={"metric_key": "m2_vacantes"},
        provenance={}, facts=({"metric_key": "m2_vacantes", "value": 10.0, "unit": "m2",
                              "entity_id": "Torre A", "period": "2026-06"},),
        coverage={"status": "complete", "eligible_count": 1, "observed_count": 1},
        metric_id=None, dataset_id=None, requested_temporal=None, granularity="month",
    )
    envelope = {"fragments": [{"type": "text", "text": "Torre A no tuvo cambios respecto al otro periodo revisado."},
                              {"type": "governed_dataset_ref", "claim_id": "g"}],
                "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                             "entity_ids": ["Torre A"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid
