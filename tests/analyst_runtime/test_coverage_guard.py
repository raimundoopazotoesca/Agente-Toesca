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
    assert result.valid and result.content == "Fue 5.945%"


def test_canonical_conflict_fails_closed_unchanged():
    envelope = {"fragments": [{"type": "canonical_metric_ref", "claim_id": "c"}],
                "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", "metric_key": "vacancia", "value": 5.39, "unit": "%", "entity_id": "A", "period": "2026-06"}]}
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [])
    assert not result.valid and result.content == "vacancia: 5.945%"


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
    assert result.content.startswith("Cobertura parcial: observados 2 de 3 miembros aplicables.")


def test_unknown_scope_renders_deterministic_uncertainty_language(catalog_db):
    evidence = _governed_evidence(_rows("Torre A"), {"status": "unknown", "eligible_count": None, "observed_count": 1})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A"], "period": "2026-06", "universe_kind": "fund_assets"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid
    assert "no puede garantizarse completitud" in result.content.lower()


def test_explicit_three_asset_subset_is_complete_over_the_subset(catalog_db):
    evidence = _governed_evidence(_rows("Torre A", "Boulevard", "Parking PT"),
                                    {"status": "complete", "eligible_count": 3, "observed_count": 3})
    envelope = {"fragments": [{"type": "governed_dataset_ref", "claim_id": "g"}], "canonical_metric_claims": [],
                "governed_dataset_claims": [{"claim_id": "g", "evidence_id": "g1", "metric_key": "m2_vacantes",
                                              "entity_ids": ["Torre A", "Boulevard", "Parking PT"], "period": "2026-06", "universe_kind": "explicit_subset"}]}
    result = validate_and_render(envelope, [], [evidence], catalog_db)
    assert result.valid
    assert "Cobertura parcial" not in result.content


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
