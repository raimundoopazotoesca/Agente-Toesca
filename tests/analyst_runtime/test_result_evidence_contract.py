"""A3.2a focused tests: the ToolResult/ToolEvidence contract itself --
construction, invariants, derivation rules, and serialization. Not producer
or consumer behavior (those are covered by the existing guard/session
suites, which this slice deliberately leaves passing unchanged).
"""
from __future__ import annotations

import json

import pytest

from tools.analyst_runtime.transport import (Authority, Producer, ResultEnvelope, Temporal, ToolEvidence,
                                              ToolResult, Units, evidence_from_dict, evidence_to_dict)


def _canonical_evidence(evidence_id: str = "e1") -> ToolEvidence:
    return ToolEvidence.build(
        evidence_id=evidence_id, evidence_class="canonical_metric", tool_name="analytics_lookup_asset",
        source_kind="raw_eeff_line", scope={"asset": "PT"}, semantic_contract={"metric_key": "noi"},
        provenance={"ingest_run_id": 7}, facts=({"metric_key": "noi", "value": 100.0, "unit": "UF",
                                                  "entity_id": "PT", "period": "2026-06"},),
        metric_id="noi", requested_temporal={"period": "2026-06"},
    )


# ---------------------------------------------------------------------------
# ToolResult construction and the ok=False -> evidence=None invariant
# ---------------------------------------------------------------------------

def test_tool_result_constructs_with_all_fields():
    evidence = _canonical_evidence()
    result = ToolResult(call_id="c1", ok=True, content="{}", trace={"tool_name": "x"}, control=None, evidence=evidence)
    assert result.call_id == "c1" and result.ok and result.evidence is evidence


def test_ok_false_with_evidence_is_rejected():
    with pytest.raises(ValueError):
        ToolResult(call_id="c1", ok=False, content="{}", evidence=_canonical_evidence())


def test_ok_false_without_evidence_is_valid():
    result = ToolResult(call_id="c1", ok=False, content='{"error": "boom"}', trace={"error": "boom"})
    assert not result.ok and result.evidence is None


def test_technical_error_fields_live_on_content_trace_control_not_evidence():
    result = ToolResult(call_id="c1", ok=False, content='{"error_type": "invalid_request"}',
                         trace={"error": "bad args"}, control={"kind": "semantic_rejection"})
    assert result.evidence is None
    assert "error" in result.trace
    assert result.control["kind"] == "semantic_rejection"


# ---------------------------------------------------------------------------
# ToolEvidence construction / all four evidence classes / authority.kind
# ---------------------------------------------------------------------------

def test_canonical_metric_evidence_construction():
    evidence = _canonical_evidence()
    assert evidence.evidence_class == "canonical_metric"
    assert evidence.authority.kind == "canonical_metric"
    assert evidence.producer.tool_name == "analytics_lookup_asset"
    assert evidence.result.kind == "scalar"


def test_governed_dataset_evidence_construction():
    evidence = ToolEvidence.build(
        evidence_id="e2", evidence_class="governed_dataset", tool_name="analytics_breakdown_asset",
        source_kind="canonical", scope={"fund": "PT"}, semantic_contract={}, provenance={},
        facts=({"metric_key": "noi", "value": 1.0, "unit": "UF", "entity_id": "A", "period": "2026-06"},
               {"metric_key": "noi", "value": 2.0, "unit": "UF", "entity_id": "B", "period": "2026-06"}),
    )
    assert evidence.evidence_class == "governed_dataset"
    assert evidence.authority.kind == "governed_dataset"
    assert evidence.result.kind == "table"
    assert evidence.result.returned_rows == 2


def test_verified_query_evidence_construction():
    """No producer exists for verified_query yet (out of scope for A3.2a):
    the contract itself must still accept the class."""
    evidence = ToolEvidence.build(
        evidence_id="e3", evidence_class="verified_query", tool_name="future_tool", source_kind="rent_roll",
        scope={}, semantic_contract={}, provenance={}, facts=({"metric_key": "gla", "value": 100.0,
                                                                "unit": "m2", "entity_id": "A", "period": "2026-06"},),
    )
    assert evidence.evidence_class == "verified_query"
    assert evidence.authority.kind == "verified_query"


def test_controlled_sql_evidence_construction_with_empty_facts():
    evidence = ToolEvidence(
        evidence_id="e4", evidence_class="controlled_sql",
        producer=Producer(tool_name="future_sql_tool"),
        authority=Authority(kind="controlled_sql", sql_fingerprint="sha256:abc", source_system="agente_toesca_v2.db"),
        scope={}, temporal=Temporal(), units=Units(),
        result=ResultEnvelope(kind="table", columns=("fondo_key", "noi_clp"),
                               rows=({"fondo_key": "PT", "noi_clp": 1000.0},),
                               total_rows=None, returned_rows=1, truncated=False, has_more=False),
        facts=(),
    )
    assert evidence.facts == ()
    assert evidence.result.rows[0]["fondo_key"] == "PT"


def test_controlled_sql_with_nonempty_facts_is_rejected():
    with pytest.raises(ValueError, match="controlled_sql"):
        ToolEvidence(
            evidence_id="e5", evidence_class="controlled_sql",
            producer=Producer(tool_name="t"), authority=Authority(kind="controlled_sql"),
            scope={}, temporal=Temporal(), units=Units(), result=ResultEnvelope(kind="empty"),
            facts=({"metric_key": "x", "value": 1.0, "unit": None, "entity_id": "A", "period": None},),
        )


def test_unknown_evidence_class_is_rejected():
    with pytest.raises(ValueError, match="evidence_class"):
        ToolEvidence.build(evidence_id="e6", evidence_class="made_up_class", tool_name="t", source_kind=None,
                            scope={}, semantic_contract={}, provenance={}, facts=())


def test_authority_kind_must_equal_evidence_class():
    with pytest.raises(ValueError, match="authority.kind"):
        ToolEvidence(
            evidence_id="e7", evidence_class="canonical_metric",
            producer=Producer(tool_name="t"), authority=Authority(kind="governed_dataset"),
            scope={}, temporal=Temporal(), units=Units(), result=ResultEnvelope(kind="empty"), facts=(),
        )


# ---------------------------------------------------------------------------
# producer / authority: required vs optional, no fabricated IDs/versions
# ---------------------------------------------------------------------------

def test_producer_carries_tool_name_and_contract_version():
    evidence = _canonical_evidence()
    assert evidence.producer.tool_name == "analytics_lookup_asset"
    assert evidence.producer.contract_version  # non-empty, stamped


def test_authority_optional_ids_default_to_none_not_fabricated():
    evidence = ToolEvidence.build(
        evidence_id="e8", evidence_class="governed_dataset", tool_name="list_assets", source_kind="canonical",
        scope={"fund": "PT"}, semantic_contract={}, provenance={"tables": ["dim_activo"]},
        facts=({"entity_id": "PT4501", "period": None},),
    )
    # list_assets has no catalog-backed metric/dataset identity -- must stay None,
    # never derived from the table name in provenance.
    assert evidence.authority.metric_id is None
    assert evidence.authority.dataset_id is None
    assert evidence.authority.dataset_version is None
    assert evidence.authority.metric_version is None
    assert evidence.authority.verified_query_id is None
    assert evidence.authority.sql_fingerprint is None


def test_authority_metric_id_populated_only_when_explicitly_given():
    evidence = _canonical_evidence()
    assert evidence.authority.metric_id == "noi"


def test_authority_dataset_id_is_a_real_catalog_key_not_a_table_name():
    evidence = ToolEvidence.build(
        evidence_id="e9", evidence_class="governed_dataset", tool_name="analytics_query_dataset",
        source_kind="dataset", scope={}, semantic_contract={"source": "raw_rent_roll_line"}, provenance={},
        facts=({"metric_key": "gla", "value": 1.0, "unit": "m2", "entity_id": "A", "period": None},),
        dataset_id="rent_roll_units",  # the catalog key, distinct from provenance's raw table name
    )
    assert evidence.authority.dataset_id == "rent_roll_units"
    assert evidence.authority.dataset_id != evidence.semantic_contract.get("source")


def test_authority_source_system_preserves_legacy_source_kind_semantics():
    evidence = _canonical_evidence()
    assert evidence.authority.source_system == "raw_eeff_line"


# ---------------------------------------------------------------------------
# temporal: evidence-level summary vs per-fact period, no fabricated observed_as_of
# ---------------------------------------------------------------------------

def test_temporal_resolved_is_derived_from_fact_periods():
    evidence = ToolEvidence.build(
        evidence_id="e10", evidence_class="governed_dataset", tool_name="t", source_kind=None,
        scope={}, semantic_contract={}, provenance={},
        facts=({"metric_key": "m", "value": 1.0, "unit": None, "entity_id": "A", "period": "2025-07"},
               {"metric_key": "m", "value": 2.0, "unit": None, "entity_id": "A", "period": "2026-06"}),
    )
    assert evidence.temporal.resolved == {"start": "2025-07", "end": "2026-06"}
    # Per-fact period is untouched -- temporal is a summary, not a replacement.
    assert evidence.facts[0]["period"] == "2025-07"
    assert evidence.facts[1]["period"] == "2026-06"


def test_temporal_requested_defaults_to_resolved_when_not_supplied():
    evidence = ToolEvidence.build(
        evidence_id="e11", evidence_class="canonical_metric", tool_name="t", source_kind=None,
        scope={}, semantic_contract={}, provenance={},
        facts=({"metric_key": "m", "value": 1.0, "unit": None, "entity_id": "A", "period": "2026-06"},),
    )
    assert evidence.temporal.requested == evidence.temporal.resolved


def test_temporal_requested_honors_explicit_window_even_when_it_differs_from_resolved():
    evidence = ToolEvidence.build(
        evidence_id="e12", evidence_class="governed_dataset", tool_name="t", source_kind=None,
        scope={}, semantic_contract={}, provenance={},
        facts=({"metric_key": "m", "value": 1.0, "unit": None, "entity_id": "A", "period": "2026-03"},),
        requested_temporal={"period": "2026-01", "period_end": "2026-06"},
    )
    assert evidence.temporal.requested == {"period": "2026-01", "period_end": "2026-06"}
    assert evidence.temporal.resolved == {"start": "2026-03", "end": "2026-03"}


def test_temporal_resolved_is_none_for_empty_facts():
    evidence = ToolEvidence.build(evidence_id="e13", evidence_class="governed_dataset", tool_name="t",
                                   source_kind=None, scope={}, semantic_contract={}, provenance={}, facts=())
    assert evidence.temporal.resolved is None


def test_observed_as_of_is_never_fabricated():
    evidence = _canonical_evidence()
    assert evidence.temporal.observed_as_of is None


# ---------------------------------------------------------------------------
# units: evidence-level summary, heterogeneous-unit behavior
# ---------------------------------------------------------------------------

def test_units_summary_populated_when_all_facts_share_one_unit():
    evidence = _canonical_evidence()
    assert evidence.units.unit == "UF"


def test_units_summary_is_none_for_heterogeneous_facts_never_a_dominant_guess():
    evidence = ToolEvidence.build(
        evidence_id="e14", evidence_class="governed_dataset", tool_name="t", source_kind=None,
        scope={}, semantic_contract={}, provenance={},
        facts=({"metric_key": "gla_m2", "value": 100.0, "unit": "m2", "entity_id": "A", "period": None},
               {"metric_key": "unit_count", "value": 3, "unit": "rows", "entity_id": "A", "period": None}),
    )
    assert evidence.units.unit is None
    # Per-fact unit remains the authoritative source for consumers.
    assert evidence.facts[0]["unit"] == "m2" and evidence.facts[1]["unit"] == "rows"


def test_units_scale_and_basis_are_never_invented():
    evidence = _canonical_evidence()
    assert evidence.units.scale is None
    assert evidence.units.basis is None


# ---------------------------------------------------------------------------
# result: scalar/table/empty/metadata, row metadata, truncation semantics
# ---------------------------------------------------------------------------

def test_result_kind_scalar_for_single_fact():
    assert _canonical_evidence().result.kind == "scalar"


def test_result_kind_table_for_multiple_facts():
    evidence = ToolEvidence.build(
        evidence_id="e15", evidence_class="governed_dataset", tool_name="t", source_kind=None,
        scope={}, semantic_contract={}, provenance={},
        facts=({"metric_key": "m", "value": 1.0, "unit": None, "entity_id": "A", "period": None},
               {"metric_key": "m", "value": 2.0, "unit": None, "entity_id": "B", "period": None}),
    )
    assert evidence.result.kind == "table"


def test_result_kind_empty_for_zero_facts():
    evidence = ToolEvidence.build(evidence_id="e16", evidence_class="governed_dataset", tool_name="t",
                                   source_kind=None, scope={}, semantic_contract={}, provenance={}, facts=(),
                                   coverage={"status": "none"})
    assert evidence.result.kind == "empty"
    assert evidence.result.total_rows == 0
    assert evidence.result.returned_rows == 0


def test_result_kind_metadata_is_a_valid_direct_construction():
    """No live producer emits `metadata` today (rule 11 scope) -- the contract
    itself must still accept it structurally."""
    evidence = ToolEvidence(
        evidence_id="e17", evidence_class="governed_dataset",
        producer=Producer(tool_name="t"), authority=Authority(kind="governed_dataset"),
        scope={}, temporal=Temporal(), units=Units(),
        result=ResultEnvelope(kind="metadata", columns=(), rows=(), total_rows=0, returned_rows=0),
        facts=(),
    )
    assert evidence.result.kind == "metadata"


def test_result_kind_must_be_one_of_the_four_allowed_values():
    with pytest.raises(ValueError, match="kind"):
        ResultEnvelope(kind="not_a_real_kind")


def test_result_rows_mechanically_derived_from_facts_for_governed_dataset():
    facts = ({"metric_key": "m", "value": 1.0, "unit": "UF", "entity_id": "A", "period": "2026-06"},
             {"metric_key": "m", "value": 2.0, "unit": "UF", "entity_id": "B", "period": "2026-06"})
    evidence = ToolEvidence.build(evidence_id="e18", evidence_class="governed_dataset", tool_name="t",
                                   source_kind=None, scope={}, semantic_contract={}, provenance={}, facts=facts)
    assert evidence.result.rows == tuple(dict(fact) for fact in facts)
    assert set(evidence.result.columns) == {"metric_key", "value", "unit", "entity_id", "period"}


def test_result_total_rows_none_when_not_actually_known():
    """No implicit COUNT: a bounded controlled_sql result that never counted
    the full table must report total_rows=None, not a guessed number."""
    evidence = ToolEvidence(
        evidence_id="e19", evidence_class="controlled_sql",
        producer=Producer(tool_name="t"), authority=Authority(kind="controlled_sql"),
        scope={}, temporal=Temporal(), units=Units(),
        result=ResultEnvelope(kind="table", columns=("x",), rows=({"x": 1}, {"x": 2}),
                               total_rows=None, returned_rows=2, truncated=True, has_more=True,
                               omission_reason="row_limit"),
        facts=(),
    )
    assert evidence.result.total_rows is None
    assert evidence.result.truncated and evidence.result.has_more
    assert evidence.result.omission_reason == "row_limit"


def test_result_not_truncated_by_default_for_todays_producers():
    """Today's producers don't truncate anything -- the derived result must
    reflect that honestly rather than defaulting to an ambiguous state."""
    evidence = ToolEvidence.build(
        evidence_id="e20", evidence_class="governed_dataset", tool_name="t", source_kind=None,
        scope={}, semantic_contract={}, provenance={},
        facts=tuple({"metric_key": "m", "value": float(i), "unit": None, "entity_id": str(i), "period": None}
                    for i in range(50)),
    )
    assert evidence.result.truncated is False
    assert evidence.result.has_more is False
    assert evidence.result.total_rows == 50
    assert evidence.result.returned_rows == 50


def test_a_confirmed_empty_result_is_still_a_valid_evidence_object():
    evidence = ToolEvidence.build(evidence_id="e21", evidence_class="governed_dataset", tool_name="t",
                                   source_kind=None, scope={}, semantic_contract={}, provenance={}, facts=(),
                                   coverage={"status": "none", "eligible_count": 0, "observed_count": 0})
    assert evidence.result.kind == "empty"
    assert evidence.coverage["status"] == "none"


# ---------------------------------------------------------------------------
# facts default behavior / controlled_sql facts=[] invariant
# ---------------------------------------------------------------------------

def test_facts_default_to_empty_tuple():
    evidence = ToolEvidence(
        evidence_id="e22", evidence_class="controlled_sql",
        producer=Producer(tool_name="t"), authority=Authority(kind="controlled_sql"),
        scope={}, temporal=Temporal(), units=Units(), result=ResultEnvelope(kind="empty"),
    )
    assert evidence.facts == ()


def test_limitations_default_to_empty_tuple():
    assert _canonical_evidence().limitations == ()


# ---------------------------------------------------------------------------
# deterministic serialization / round trip / no arbitrary object leakage
# ---------------------------------------------------------------------------

def test_serialization_is_deterministic_across_calls():
    evidence = _canonical_evidence()
    first = json.dumps(evidence_to_dict(evidence), sort_keys=True)
    second = json.dumps(evidence_to_dict(evidence), sort_keys=True)
    assert first == second


def test_serialization_round_trips_through_dict():
    evidence = _canonical_evidence()
    restored = evidence_from_dict(evidence_to_dict(evidence))
    assert restored == evidence


def test_serialization_round_trips_controlled_sql_with_empty_facts():
    evidence = ToolEvidence(
        evidence_id="e23", evidence_class="controlled_sql",
        producer=Producer(tool_name="t"), authority=Authority(kind="controlled_sql", sql_fingerprint="sha256:xyz"),
        scope={}, temporal=Temporal(), units=Units(),
        result=ResultEnvelope(kind="table", columns=("x",), rows=({"x": 1},), total_rows=None, returned_rows=1),
        facts=(),
    )
    restored = evidence_from_dict(evidence_to_dict(evidence))
    assert restored.facts == ()
    assert restored.authority.sql_fingerprint == "sha256:xyz"


def test_serialization_output_is_json_encodable():
    payload = evidence_to_dict(_canonical_evidence())
    # json.dumps would raise TypeError if any leaf were non-scalar/non-container.
    json.dumps(payload)


def test_serialization_rejects_arbitrary_python_objects():
    class Unserializable:
        pass

    evidence = ToolEvidence.build(
        evidence_id="e24", evidence_class="canonical_metric", tool_name="t", source_kind=None,
        scope={}, semantic_contract={"bad": Unserializable()}, provenance={}, facts=(),
    )
    with pytest.raises(TypeError):
        evidence_to_dict(evidence)


def test_evidence_from_dict_rejects_missing_required_fields():
    with pytest.raises(ValueError):
        evidence_from_dict({"evidence_id": "e25"})


def test_evidence_from_dict_rejects_non_dict_payload():
    with pytest.raises(TypeError):
        evidence_from_dict("not-a-dict")  # type: ignore[arg-type]


def test_no_secrets_provider_payloads_or_cot_fields_exist_on_the_contract():
    """The contract's field set is closed and inspectable -- assert none of
    the known-forbidden field names appear anywhere in the serialized shape."""
    payload = evidence_to_dict(_canonical_evidence())

    def _walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in {"api_key", "secret", "token", "raw_provider_payload",
                                    "chain_of_thought", "reasoning", "prompt", "system_prompt"}
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
