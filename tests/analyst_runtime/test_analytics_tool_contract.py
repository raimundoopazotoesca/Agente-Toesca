from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analytics.capabilities import capability_metric_keys
from tools.analytics.catalog import load_metric_catalog
from tools.analyst_runtime.actions import (
    ActionRegistry,
    AnalyticsBreakdownAssetAction,
    AnalyticsLookupAssetAction,
    AnalyticsLookupFundAction,
    RunSqlAction,
)
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession, OpenAIResponsesAnalystSessionFactory
from tools.analyst_runtime.transport import ModelResponse, ToolRequest


DB = Path("memory/agente_toesca_v2.db")


def test_catalog_derives_capability_metric_keys_from_semantic_metadata():
    metrics = capability_metric_keys(load_metric_catalog())

    assert metrics == {
        "fund_lookup": ("ingresos_mensual_fondo", "ltv_fondo", "noi_mensual_fondo", "vacancia_pct_fondo"),
        "asset_lookup": ("ltv_activo", "m2_vacantes", "noi_mensual_activo", "vacancia_fisica_pct_activo"),
        "asset_breakdown": ("ltv_activo", "m2_vacantes", "noi_mensual_activo", "vacancia_fisica_pct_activo"),
    }


def test_lookup_fund_schema_makes_m1_grouping_unrepresentable():
    spec = AnalyticsLookupFundAction(DB).tool_spec()

    assert spec.name == "analytics_lookup_fund"
    assert spec.parameters["additionalProperties"] is False
    assert spec.parameters["properties"]["metric"]["enum"] == ["ingresos_mensual_fondo", "ltv_fondo", "noi_mensual_fondo", "vacancia_pct_fondo"]
    assert set(spec.parameters["properties"]) == {"metric", "fund", "period", "period_end", "aggregation"}
    assert set(spec.parameters["required"]) == {"metric", "fund", "period", "period_end"}
    assert spec.parameters["properties"]["period_end"]["type"] == ["string", "null"]


def test_lookup_fund_emits_traceable_evidence_for_metadata_defined_aggregate():
    action = AnalyticsLookupFundAction(DB)
    result = action.execute(ToolRequest("noi", action.name, {
        "metric": "noi_mensual_fondo", "fund": "PT", "period": "2025-01", "period_end": "2025-12", "aggregation": "sum",
    }))

    assert result.ok is True
    assert result.evidence is not None
    fact = result.evidence.facts[0]
    assert fact["value"] == pytest.approx(172868.06, abs=0.01)
    assert fact["period"] == "2025-01..2025-12"
    assert result.evidence.provenance["source_period_count"] == 12


def test_invalid_aggregation_stops_the_turn_before_unrelated_fallbacks():
    action = AnalyticsLookupFundAction(DB)
    registry = ActionRegistry([action, RunSqlAction(LiveReadOnlySandbox(DB))])

    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([ModelResponse("", [
                ToolRequest("ltv", action.name, {"metric": "ltv_fondo", "fund": "TRI", "period": "2025-01", "period_end": "2025-12", "aggregation": "sum"}),
                ToolRequest("sql", "run_sql", {"query": "SELECT 1"}),
            ])])
        def complete(self, _request): return next(self.responses)

    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("suma LTV")

    assert result.turn.raw["termination_reason"] == "semantic_rejection"
    assert [call.name for call in result.turn.tool_calls] == [action.name]
    assert result.turn.tool_calls[0].trace["semantic_rejection"]["code"] == "invalid_aggregation"
    assert "no se puede sumar" in result.turn.text.lower()


def test_semantic_rejection_returns_through_session_without_structured_finalization():
    action = AnalyticsLookupFundAction(DB)
    registry = ActionRegistry([action])

    class ScriptedTransport:
        def complete(self, _request):
            return ModelResponse("", [ToolRequest("ltv", action.name, {
                "metric": "ltv_fondo", "fund": "TRI", "period": "2025-01", "period_end": "2025-12", "aggregation": "sum",
            })])

    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()), presenter=None)
    result = session.ask("suma LTV")

    assert result.termination_reason == "semantic_rejection"
    assert result.text.lower().startswith("no se puede sumar")
    assert result.presentation_integrity_status == "semantic_rejection"


def test_lookup_fund_maps_scope_to_executor_and_preserves_semantic_trace():
    action = AnalyticsLookupFundAction(DB)
    result = action.execute(ToolRequest("call", action.name, {
        "metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06",
    }))

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["rows"][0]["value"] == pytest.approx(5.945)
    assert result.trace["arguments"] == {"metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06"}
    assert result.trace["scope"] == {"fund": "TRI"}
    assert result.trace["result"] == {
        "metric_key": "vacancia_pct_fondo", "source_kind": "canonical", "catalog_version": 1,
        "row_count": 1, "provenance_ingest_run_ids": [142],
    }


def test_lookup_asset_schema_has_no_breakdown_controls_and_maps_asset_scope():
    action = AnalyticsLookupAssetAction(DB)
    spec = action.tool_spec()
    result = action.execute(ToolRequest("call", action.name, {
        "metric": "vacancia_fisica_pct_activo", "assets": ["Apo3001"], "period": "2026-06",
    }))

    assert set(spec.parameters["properties"]) == {"metric", "assets", "period", "period_end", "aggregation"}
    assert spec.parameters["properties"]["assets"]["type"] == "array"
    assert json.loads(result.content)["rows"][0]["value"] == pytest.approx(0.3620316883)
    assert result.trace["scope"] == {"asset": "Apo3001"}


def test_breakdown_schema_cannot_select_fund_metric_and_fixes_grouping_internally():
    action = AnalyticsBreakdownAssetAction(DB)
    spec = action.tool_spec()

    assert set(spec.parameters["properties"]) == {"metric", "fund", "assets", "period", "period_end", "aggregation", "order_by", "limit"}
    assert "vacancia_pct_fondo" not in spec.parameters["properties"]["metric"]["enum"]
    assert set(spec.parameters["required"]) == {"metric", "fund", "assets", "period", "period_end", "order_by", "limit"}
    assert spec.parameters["properties"]["order_by"]["enum"] == ["value_desc", "value_asc", None]
    invalid = action.execute(ToolRequest("bad", action.name, {
        "metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06",
    }))
    valid = action.execute(ToolRequest("good", action.name, {
        "metric": "m2_vacantes", "fund": "TRI", "period": "2026-06", "order_by": "value_desc", "limit": 10,
    }))

    assert json.loads(invalid.content)["error_type"] == "invalid_request"
    rows = json.loads(valid.content)["rows"]
    assert [row["entity_id"] for row in rows[:3]] == ["Mall Curicó", "Apo3001", "Viña Centro"]
    assert valid.trace["scope"] == {"fund": "TRI"}


def test_scripted_capabilities_dispatch_lookup_breakdown_and_sql():
    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("fund", "analytics_lookup_fund", {
                    "metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06",
                })]),
                ModelResponse("", [ToolRequest("breakdown", "analytics_breakdown_asset", {
                    "metric": "m2_vacantes", "fund": "TRI", "period": "2026-06", "order_by": "value_desc", "limit": 10,
                })]),
                ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT 1"})]),
                ModelResponse("respuesta"),
            ])

        def complete(self, _request):
            return next(self.responses)

    registry = ActionRegistry([
        RunSqlAction(LiveReadOnlySandbox(DB)), AnalyticsLookupFundAction(DB),
        AnalyticsLookupAssetAction(DB), AnalyticsBreakdownAssetAction(DB),
    ])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")

    assert [(call.name, call.ok) for call in result.turn.tool_calls] == [
        ("analytics_lookup_fund", True), ("analytics_breakdown_asset", True), ("run_sql", True),
    ]
    assert result.turn.tool_calls[1].trace["result"]["source_kind"] == "breakdown"


def test_alpha_factory_exposes_only_capabilities_and_run_sql():
    factory = OpenAIResponsesAnalystSessionFactory(DB, client_factory=lambda: object(), presenter_factory=None)
    registry = factory.create(None, [])._loop.action_executor

    assert set(registry._by_name) == {
        "run_sql", "schema_search", "analytics_lookup_fund", "analytics_lookup_asset", "analytics_breakdown_asset", "analytics_account_query",
        "resolve_entity", "list_assets",
    }
