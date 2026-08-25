from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.transport import ToolEvidence


CANONICAL_EVIDENCE = ToolEvidence(
    "e1", "canonical_metric",
    facts=({"metric_key": "vacancia", "value": 5.945, "unit": "%", "entity_id": "A", "period": "2026-06"},),
)


@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_activo (activo_key TEXT, fondo_key TEXT)")
    conn.executemany("INSERT INTO dim_activo VALUES (?, ?)", [
        ("Torre A", "PT"), ("Boulevard", "PT"), ("Parking PT", "PT"), ("Apo3001", "TRI"),
    ])
    conn.commit()
    conn.close()
    return path


def _governed_evidence(facts, coverage, scope=None):
    return ToolEvidence(
        "g1", "governed_dataset", scope=scope or {"fund": "PT"},
        semantic_contract={"metric_key": "m2_vacantes"}, coverage=coverage, facts=facts,
    )


# ---- Parity with Stage 5.3 canonical_guard: pure canonical envelopes ----

def test_canonical_only_envelope_renders_identically_to_stage_5_3():
    envelope = {"fragments": [{"type": "text", "text": "Fue "}, {"type": "canonical_metric_ref", "claim_id": "c"}],
                "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", "metric_key": "vacancia", "value": 5.945, "unit": "%", "entity_id": "A", "period": "2026-06"}]}
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [])
    assert result.valid and result.content == "Fue 5,95%"


def test_canonical_conflict_fails_closed_unchanged():
    envelope = {"fragments": [{"type": "canonical_metric_ref", "claim_id": "c"}],
                "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", "metric_key": "vacancia", "value": 5.39, "unit": "%", "entity_id": "A", "period": "2026-06"}]}
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [])
    assert not result.valid and result.content == "vacancia: 5,95%"


# ---- Governed dataset: complete / partial / unknown ----

def _rows(*entities):
    return tuple({"metric_key": "m2_vacantes", "value": 10.0, "unit": "m2", "entity_id": e, "period": "2026-06"} for e in entities)


def test_complete_fund_enumeration_renders_without_caveat(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard", "Parking PT"),
                                    {"status": "complete", "eligible_count": 3, "observed_count": 3})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A", "Boulevard", "Parking PT"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid
    assert "Cobertura parcial" not in result.content
    assert "Torre A" in result.content and "Boulevard" in result.content


def test_partial_fund_enumeration_renders_deterministic_caveat(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard"),
                                    {"status": "partial", "eligible_count": 3, "observed_count": 2})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A", "Boulevard"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid
    assert result.content.startswith("Ojo: estos datos alcanzan a 2 de 3 elementos aplicables")


def test_unknown_scope_renders_deterministic_uncertainty_language(catalog_db):
    evidence = _governed_evidence(_rows("Torre A"), {"status": "unknown", "eligible_count": None, "observed_count": 1})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid
    assert "no es posible confirmar que estos datos representen el conjunto completo" in result.content.lower()


def test_explicit_three_asset_subset_is_complete_over_the_subset(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard", "Parking PT"),
                                    {"status": "complete", "eligible_count": 3, "observed_count": 3})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A", "Boulevard", "Parking PT"], "period": "2026-06", "universe_kind": "explicit_subset"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid
    assert "Cobertura parcial" not in result.content


# ---- P0: fail-closed content is never empty ----

def test_fail_closed_with_no_canonical_or_governed_evidence_is_never_empty():
    """A turn that only ran run_sql (which emits no ToolEvidence) and produced
    a rejected envelope used to fall through every branch in `_fail` with
    nothing to render, leaving `content == ""` -- a blank visible_answer with
    no explanation. This is the exact shape hit live on "valor cuota
    contable" and "GLA por rubro" (see docs/toesca-data-semantic-architecture
    coverage audit): correct SQL, rejected envelope, silent empty answer."""
    envelope = {"fragments": [{"type": "canonical_metric_ref", "claim_id": "missing"}],
                "canonical_metric_claims": [], "governed_dataset_claims": []}
    result = validate_and_render(envelope, [], [])
    assert not result.valid
    assert result.content != ""
    assert "no puedo confirmar" in result.content.lower()


# ---- Entity provenance guard: text/raw_text bypass ----

def test_raw_sql_enumeration_of_multiple_same_fund_assets_fails_closed(catalog_db):
    envelope = {"fragments": [{"type": "raw_text", "text": "Los activos de PT son Torre A, Boulevard y Parking PT."}],
                "canonical_metric_claims": [], "governed_dataset_claims": []}
    result = validate_and_render(envelope, [], [], catalog_db)
    assert not result.valid
    assert "no puedo confirmar" in result.content.lower()


def test_raw_single_asset_mention_is_permitted(catalog_db):
    envelope = {"fragments": [{"type": "raw_text", "text": "Apo3001 tuvo vacancia alta este mes."}],
                "canonical_metric_claims": [], "governed_dataset_claims": []}
    result = validate_and_render(envelope, [], [], catalog_db)
    assert result.valid
    assert "Apo3001" in result.content


def test_governed_backed_entities_in_raw_text_are_not_blocked(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard"),
                                    {"status": "complete", "eligible_count": 2, "observed_count": 2})
    envelope = {"fragments": [{"type": "raw_text", "text": "Torre A y Boulevard son los activos relevantes."}],
                "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A", "Boulevard"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid


# ---- Vague-referent guard: multi-component breakdown must name real entities ----

def _breakdown_envelope(text: str, extra_derived: list | None = None):
    return {
        "fragments": [{"type": "text", "text": text}, {"type": "governed_dataset_ref", "claim_id": "g"}],
        "canonical_metric_claims": [],
        "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                      "entity_ids": ["Torre A", "Boulevard"], "period": "2026-06", "universe_kind": "fund_assets"}],
        "derived_metric_claims": extra_derived or [],
    }


def test_vague_placeholder_for_a_known_component_entity_fails_closed(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard"),
                                    {"status": "complete", "eligible_count": 2, "observed_count": 2})
    envelope = _breakdown_envelope("Uno de los activos tiene más vacancia que el otro activo.")
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert not result.valid
    assert result.trace["reason"] == "vague_entity_reference"


def test_vague_placeholder_fallback_still_lists_the_real_entities(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard"),
                                    {"status": "complete", "eligible_count": 2, "observed_count": 2})
    envelope = _breakdown_envelope("Uno de los activos tiene más vacancia que el otro activo.")
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert "Torre A" in result.content and "Boulevard" in result.content


def test_single_component_context_permits_vague_language(catalog_db):
    # Only one entity is bound for this metric+period -- the multi-component
    # guard must not fire on unrelated prose that happens to contain "otro".
    evidence = _governed_evidence(_rows("Torre A"), {"status": "complete", "eligible_count": 1, "observed_count": 1})
    envelope = {"fragments": [{"type": "text", "text": "Torre A no tuvo cambios respecto al otro periodo revisado."},
                               {"type": "governed_dataset_ref", "claim_id": "g"}],
                "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid


# ---- Qualitative comparison guard: greater/less must be claim-bound, not free text ----

def test_free_text_superlative_between_two_components_fails_closed(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard"),
                                    {"status": "complete", "eligible_count": 2, "observed_count": 2})
    envelope = _breakdown_envelope("Torre A exhibe la mayor tasa de vacancia física.")
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert not result.valid
    assert result.trace["reason"] == "unbound_qualitative_comparison"


def test_superlative_backed_by_a_comparison_claim_is_permitted():
    canonical_a = ToolEvidence("ea", "canonical_metric",
        facts=({"metric_key": "vacancia_fisica_pct_activo", "value": 7.84, "unit": "%", "entity_id": "Apo4501", "period": "2026-06"},))
    canonical_b = ToolEvidence("eb", "canonical_metric",
        facts=({"metric_key": "vacancia_fisica_pct_activo", "value": 22.91, "unit": "%", "entity_id": "Apo4700", "period": "2026-06"},))
    envelope = {
        "fragments": [
            {"type": "canonical_metric_ref", "claim_id": "ca"}, {"type": "text", "text": " "},
            {"type": "derived_metric_ref", "claim_id": "d1"}, {"type": "text", "text": " "},
            {"type": "canonical_metric_ref", "claim_id": "cb"},
        ],
        "canonical_metric_claims": [
            {"claim_id": "ca", "evidence_id": "ea", "metric_key": "vacancia_fisica_pct_activo", "value": 7.84, "unit": "%", "entity_id": "Apo4501", "period": "2026-06"},
            {"claim_id": "cb", "evidence_id": "eb", "metric_key": "vacancia_fisica_pct_activo", "value": 22.91, "unit": "%", "entity_id": "Apo4700", "period": "2026-06"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "comparison", "lhs_claim_id": "ca", "rhs_claim_id": "cb"}],
    }
    result = validate_and_render(envelope, [canonical_a, canonical_b], [])
    assert result.valid
    assert "es menor que" in result.content


def test_comparison_operation_direction_is_computed_from_real_values_not_claim_order():
    # lhs (Apo4700, 22.91) > rhs (Apo4501, 7.84): must render "mayor", never
    # "menor" regardless of which claim the model happened to list first.
    canonical_a = ToolEvidence("ea", "canonical_metric",
        facts=({"metric_key": "vacancia_fisica_pct_activo", "value": 7.84, "unit": "%", "entity_id": "Apo4501", "period": "2026-06"},))
    canonical_b = ToolEvidence("eb", "canonical_metric",
        facts=({"metric_key": "vacancia_fisica_pct_activo", "value": 22.91, "unit": "%", "entity_id": "Apo4700", "period": "2026-06"},))
    envelope = {
        "fragments": [{"type": "canonical_metric_ref", "claim_id": "cb"}, {"type": "derived_metric_ref", "claim_id": "d1"}, {"type": "canonical_metric_ref", "claim_id": "ca"}],
        "canonical_metric_claims": [
            {"claim_id": "ca", "evidence_id": "ea", "metric_key": "vacancia_fisica_pct_activo", "value": 7.84, "unit": "%", "entity_id": "Apo4501", "period": "2026-06"},
            {"claim_id": "cb", "evidence_id": "eb", "metric_key": "vacancia_fisica_pct_activo", "value": 22.91, "unit": "%", "entity_id": "Apo4700", "period": "2026-06"},
        ],
        "governed_dataset_claims": [],
        "derived_metric_claims": [{"claim_id": "d1", "operation": "comparison", "lhs_claim_id": "cb", "rhs_claim_id": "ca"}],
    }
    result = validate_and_render(envelope, [canonical_a, canonical_b], [])
    assert result.valid
    assert "es mayor que" in result.content


# ---- Structural claim-binding failures ----

def test_governed_claim_with_invalid_evidence_id_fails(catalog_db):
    evidence = _governed_evidence(_rows("Torre A"), {"status": "complete", "eligible_count": 1, "observed_count": 1})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "does-not-exist", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert not result.valid


def test_governed_claim_entity_not_present_in_evidence_fails(catalog_db):
    evidence = _governed_evidence(_rows("Torre A"), {"status": "complete", "eligible_count": 1, "observed_count": 1})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Boulevard"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert not result.valid


def test_governed_dataset_ref_with_unknown_claim_id_fails(catalog_db):
    evidence = _governed_evidence(_rows("Torre A"), {"status": "complete", "eligible_count": 1, "observed_count": 1})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "missing"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert not result.valid


# ---- Golden: canonical KPI fallback never leaks internal metric/unit keys ----

def test_canonical_conflict_fallback_uses_catalog_display_name_and_human_unit():
    """Alpha Product Validation v1, Hallazgo #2 (cases 01, 11): a real catalog
    metric_key/unit code (e.g. 'vacancia_pct_fondo' / 'pct_0_100') must never
    reach the user even on the fail-closed path; the catalog's display_name
    and a human unit label must be used instead."""
    real_metric_evidence = ToolEvidence(
        "e1", "canonical_metric",
        facts=({"metric_key": "vacancia_pct_fondo", "value": 5.945, "unit": "pct_0_100",
                "entity_id": "TRI", "period": "2026-06"},),
    )
    envelope = {"fragments": [{"type": "canonical_metric_ref", "claim_id": "c"}],
                "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", "metric_key": "vacancia_pct_fondo",
                                              "value": 5.39, "unit": "pct_0_100", "entity_id": "TRI", "period": "2026-06"}]}
    result = validate_and_render(envelope, [real_metric_evidence], [])
    assert not result.valid
    assert "vacancia_pct_fondo" not in result.content
    assert "pct_0_100" not in result.content
    assert result.content == "Vacancia del fondo: 5,95%"


def test_trace_reports_required_coverage_fields(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard"),
                                    {"status": "partial", "eligible_count": 3, "observed_count": 2})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A", "Boulevard"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    for key in ("coverage_validation_applied", "coverage_scope", "coverage_universe_kind",
                "coverage_expected_count", "coverage_observed_count", "coverage_status",
                "coverage_gap_count", "coverage_validation_result", "entity_provenance_validation"):
        assert key in result.trace
    assert result.trace["coverage_status"] == "partial"
    assert result.trace["coverage_gap_count"] == 1
