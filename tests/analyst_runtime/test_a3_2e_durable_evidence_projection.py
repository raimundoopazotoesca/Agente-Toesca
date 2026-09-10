"""A3.2e focused tests: the ToolEvidence <-> DurableEvidenceProjection
contract itself (project_evidence_for_durable_storage /
reconstruct_durable_evidence). Not persistence (tests/analyst_workspace
covers store.py) and not restart/session behavior (covered there too).
"""
from __future__ import annotations

import pytest

from tools.analyst_runtime.transport import (
    Authority,
    DURABLE_EVIDENCE_PROJECTION_VERSION,
    DurableProjectionError,
    Producer,
    ResultEnvelope,
    Temporal,
    ToolEvidence,
    Units,
    project_evidence_for_durable_storage,
    reconstruct_durable_evidence,
)


def _canonical_evidence(evidence_id: str = "e1") -> ToolEvidence:
    return ToolEvidence.build(
        evidence_id=evidence_id, evidence_class="canonical_metric", tool_name="analytics_lookup_asset",
        source_kind="raw_eeff_line", scope={"asset": "PT"}, semantic_contract={"metric_key": "noi"},
        provenance={"ingest_run_id": 7}, facts=({"metric_key": "noi", "value": 100.0, "unit": "UF",
                                                  "entity_id": "PT", "period": "2026-06"},),
        metric_id="noi", dataset_id=None, requested_temporal={"period": "2026-06"},
        limitations=("partial_quarter",), row_limit=None,
    )


def _governed_evidence(evidence_id: str = "e2") -> ToolEvidence:
    return ToolEvidence.build(
        evidence_id=evidence_id, evidence_class="governed_dataset", tool_name="analytics_query_dataset",
        source_kind="raw_rent_roll_line", scope={"fund": "TRI"}, semantic_contract={"dataset": "vacancia"},
        provenance={"ingest_run_id": 9}, facts=(
            {"metric_key": "vacancia_pct", "value": 5.0, "unit": "pct", "entity_id": "TRI", "period": "2026-05"},
            {"metric_key": "vacancia_pct", "value": 6.0, "unit": "pct", "entity_id": "TRI", "period": "2026-06"},
        ),
        dataset_id="vacancia_mensual", coverage={"status": "complete"},
    )


def _controlled_sql_evidence(evidence_id: str = "e3") -> ToolEvidence:
    return ToolEvidence(
        evidence_id=evidence_id, evidence_class="controlled_sql",
        producer=Producer(tool_name="run_sql"), authority=Authority(kind="controlled_sql", sql_fingerprint="sha256:abc"),
        scope={}, temporal=Temporal(), units=Units(),
        result=ResultEnvelope(kind="table", columns=("fund", "noi"), rows=({"fund": "PT", "noi": 100.0},),
                              total_rows=None, returned_rows=1),
        facts=(), provenance={"sql": "SELECT fund, noi FROM v_noi"},
    )


# ---------------------------------------------------------------------------
# A/B: projection round-trip (canonical + governed)
# ---------------------------------------------------------------------------

def test_canonical_evidence_round_trips_through_durable_projection():
    evidence = _canonical_evidence()
    projection = project_evidence_for_durable_storage(evidence)
    restored = reconstruct_durable_evidence(projection)
    assert restored.evidence_id == evidence.evidence_id
    assert restored.evidence_class == "canonical_metric"
    assert restored.facts == evidence.facts
    assert restored.authority == evidence.authority
    assert restored.temporal == evidence.temporal
    assert restored.units == evidence.units
    assert restored.provenance == evidence.provenance
    assert restored.limitations == evidence.limitations
    assert restored.coverage == evidence.coverage
    assert restored.semantic_contract == evidence.semantic_contract
    assert restored.scope == evidence.scope


def test_governed_evidence_round_trips_through_durable_projection():
    evidence = _governed_evidence()
    projection = project_evidence_for_durable_storage(evidence)
    restored = reconstruct_durable_evidence(projection)
    assert restored.evidence_id == evidence.evidence_id
    assert restored.evidence_class == "governed_dataset"
    assert restored.facts == evidence.facts
    assert restored.authority == evidence.authority
    assert restored.temporal == evidence.temporal
    assert restored.units == evidence.units
    assert restored.coverage == evidence.coverage


# ---------------------------------------------------------------------------
# C: authority preservation, field by field
# ---------------------------------------------------------------------------

def test_authority_fields_preserved_individually():
    evidence = ToolEvidence.build(
        evidence_id="e4", evidence_class="canonical_metric", tool_name="analytics_lookup_fund",
        source_kind="raw_eeff_line", scope={"fund": "PT"}, semantic_contract={"metric_key": "ltv"},
        provenance={}, facts=({"metric_key": "ltv", "value": 40.0, "unit": "pct", "entity_id": "PT", "period": "2026-06"},),
        metric_id="ltv", dataset_id="ltv_catalog",
    )
    projection = project_evidence_for_durable_storage(evidence)
    restored = reconstruct_durable_evidence(projection)
    assert restored.authority.kind == "canonical_metric"
    assert restored.authority.metric_id == "ltv"
    assert restored.authority.dataset_id == "ltv_catalog"
    assert restored.authority.source_system == "raw_eeff_line"
    # Fields never populated by this producer must stay None -- never a
    # fabricated/guessed value.
    assert restored.authority.verified_query_id is None
    assert restored.authority.sql_fingerprint is None
    assert restored.authority.dataset_version is None
    assert restored.authority.metric_version is None


# ---------------------------------------------------------------------------
# D: temporal preservation
# ---------------------------------------------------------------------------

def test_temporal_fields_preserved():
    evidence = _governed_evidence()
    assert evidence.temporal.resolved == {"start": "2026-05", "end": "2026-06"}
    restored = reconstruct_durable_evidence(project_evidence_for_durable_storage(evidence))
    assert restored.temporal.requested == evidence.temporal.requested
    assert restored.temporal.resolved == evidence.temporal.resolved
    assert restored.temporal.observed_as_of == evidence.temporal.observed_as_of
    assert restored.temporal.granularity == evidence.temporal.granularity


# ---------------------------------------------------------------------------
# E: units preservation
# ---------------------------------------------------------------------------

def test_units_fields_preserved():
    evidence = _governed_evidence()
    assert evidence.units.unit == "pct"
    restored = reconstruct_durable_evidence(project_evidence_for_durable_storage(evidence))
    assert restored.units.unit == evidence.units.unit
    assert restored.units.scale == evidence.units.scale
    assert restored.units.basis == evidence.units.basis


# ---------------------------------------------------------------------------
# F: facts preservation
# ---------------------------------------------------------------------------

def test_facts_are_preserved_exactly():
    evidence = _governed_evidence()
    restored = reconstruct_durable_evidence(project_evidence_for_durable_storage(evidence))
    assert restored.facts == evidence.facts
    assert len(restored.facts) == 2


# ---------------------------------------------------------------------------
# G: result / rows exclusion
# ---------------------------------------------------------------------------

def test_result_and_rows_never_appear_in_the_durable_projection():
    evidence = _canonical_evidence()
    assert evidence.result.kind == "scalar"
    assert evidence.result.rows  # sanity: the source evidence really does carry rows
    projection = project_evidence_for_durable_storage(evidence)
    assert "result" not in projection
    assert "rows" not in projection
    import json
    assert '"rows"' not in json.dumps(projection)


def test_result_is_excluded_even_for_table_shaped_evidence():
    evidence = _governed_evidence()
    assert evidence.result.kind == "table"
    assert evidence.result.rows
    projection = project_evidence_for_durable_storage(evidence)
    assert "result" not in projection
    reconstructed = reconstruct_durable_evidence(projection)
    # The reconstructed object carries an honest empty placeholder, never a
    # resurrection of the original display rows.
    assert reconstructed.result.kind == "empty"
    assert reconstructed.result.rows == ()


def test_reconstructed_evidence_result_is_always_empty_placeholder():
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    restored = reconstruct_durable_evidence(projection)
    assert restored.result == ResultEnvelope(kind="empty")


# ---------------------------------------------------------------------------
# controlled_sql / verified_query: never projected
# ---------------------------------------------------------------------------

def test_controlled_sql_evidence_is_never_projected():
    assert project_evidence_for_durable_storage(_controlled_sql_evidence()) is None


def test_verified_query_class_is_never_projected():
    # verified_query has no producer yet; construct the ToolEvidence directly
    # to exercise the projection boundary without needing a real producer.
    evidence = ToolEvidence(
        evidence_id="e5", evidence_class="verified_query",
        producer=Producer(tool_name="hypothetical_verified_query_tool"),
        authority=Authority(kind="verified_query", verified_query_id="vq1"),
        scope={}, temporal=Temporal(), units=Units(),
        result=ResultEnvelope(kind="scalar", columns=("x",), rows=({"x": 1},), returned_rows=1),
        facts=({"metric_key": "x", "value": 1, "unit": None, "entity_id": "PT", "period": "2026-06"},),
    )
    assert project_evidence_for_durable_storage(evidence) is None


# ---------------------------------------------------------------------------
# J (transport level): unknown / missing projection_version fails closed
# ---------------------------------------------------------------------------

def test_reconstruct_rejects_missing_projection_version():
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    del projection["projection_version"]
    with pytest.raises(DurableProjectionError, match="projection_version"):
        reconstruct_durable_evidence(projection)


def test_reconstruct_rejects_unknown_projection_version():
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    projection["projection_version"] = "99"
    with pytest.raises(DurableProjectionError, match="projection_version"):
        reconstruct_durable_evidence(projection)


def test_reconstruct_rejects_non_durable_evidence_class():
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    projection["evidence_class"] = "controlled_sql"
    with pytest.raises(DurableProjectionError, match="evidence_class"):
        reconstruct_durable_evidence(projection)


def test_reconstruct_rejects_missing_authority_block():
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    del projection["authority"]
    with pytest.raises(DurableProjectionError, match="authority"):
        reconstruct_durable_evidence(projection)


def test_reconstruct_never_infers_authority_from_other_fields():
    """Even a projection with a perfectly plausible evidence_class/semantic_contract/
    provenance must be rejected if authority.kind is absent -- authority is never
    an implicit substitute for the other three (A3.2e architecture decision memo,
    section D)."""
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    projection["authority"] = {}  # kind missing
    with pytest.raises(DurableProjectionError, match="authority.kind"):
        reconstruct_durable_evidence(projection)


def test_reconstruct_rejects_non_dict_payload():
    with pytest.raises(DurableProjectionError):
        reconstruct_durable_evidence("not-a-dict")  # type: ignore[arg-type]


def test_projection_version_constant_is_stamped_on_every_projection():
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    assert projection["projection_version"] == DURABLE_EVIDENCE_PROJECTION_VERSION
