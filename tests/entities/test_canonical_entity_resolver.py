from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.analyst_runtime.actions import ActionRegistry, AnalyticsLookupAssetAction, ResolveEntityAction, RunSqlAction, SchemaSearchAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ModelResponse, ToolRequest
from tools.entities.resolver import EntityResolver


DB = Path("memory/agente_toesca_v2.db")


def test_resolver_golden_normalization_and_safe_outcomes():
    resolver = EntityResolver(DB)
    expected = {
        "Apoquindo 3001": ("resolved", "Apo3001", "exact_display"),
        "Apo3001": ("resolved", "Apo3001", "exact_key"),
        "Apoquindo-3001": ("resolved", "Apo3001", "exact_display"),
        "Mall Curicó": ("resolved", "Mall Curicó", "exact_key"),
        "Viña Centro": ("resolved", "Viña Centro", "exact_key"),
        "Parking Parque Titanium (SABA)": ("resolved", "Parking PT", "exact_display"),
    }
    for query, (status, key, kind) in expected.items():
        result = resolver.resolve(query, ("asset",))
        assert (result.status, result.candidates[0].entity_key, result.candidates[0].match_kind) == (status, key, kind)
    assert resolver.resolve("TRI", ("fund",)).candidates[0].entity_key == "TRI"
    assert resolver.resolve("Parque Titanium", ("asset",)).status == "low_confidence"
    assert resolver.resolve("activo inexistente", ("asset",)).status == "not_found"


def test_resolve_entity_action_serializes_safe_trace_and_m3_key_propagates():
    action = ResolveEntityAction(DB)
    result = action.execute(ToolRequest("resolve", action.name, {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None}))
    payload = json.loads(result.content)
    assert result.ok and payload["candidates"][0]["entity_key"] == "Apo3001"
    assert result.trace["status"] == "resolved"

    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("resolve", "resolve_entity", {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None})]),
                ModelResponse("", [ToolRequest("schema", "schema_search", {"query": "unidades espacios vacantes activo periodo", "limit": 10})]),
                ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT unidad, m2 FROM v_rent_roll_semantic WHERE activo_key='Apo3001' AND periodo='2026-06' AND is_current=1 AND occupancy_status='vacant'"})]),
                ModelResponse("respuesta"),
            ])
        def complete(self, _request): return next(self.responses)
    registry = ActionRegistry([ResolveEntityAction(DB), SchemaSearchAction(DB), RunSqlAction(LiveReadOnlySandbox(DB))])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")
    assert [call.name for call in result.turn.tool_calls] == ["resolve_entity", "schema_search", "run_sql"]
    assert "Apo3001" in result.turn.tool_calls[2].args["query"]
    payload = json.loads(result.round_trajectory[-2].tool_results[0].content)
    assert payload["row_count"] == 10
    m2_index = payload["columns"].index("m2")
    assert sum(row[m2_index] for row in payload["rows"]) == pytest.approx(1656.6)


def test_resolver_distinguishes_ambiguous_fixture_from_low_confidence(tmp_path: Path):
    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE dim_activo (activo_key TEXT, nombre TEXT, fondo_key TEXT, sociedad_key TEXT, vigente_hasta TEXT)")
    conn.executemany("INSERT INTO dim_activo VALUES (?, ?, 'TRI', NULL, NULL)", [("north-a", "Centro Norte"), ("north-b", "Centro Norte")])
    conn.commit()
    conn.close()

    result = EntityResolver(db_path).resolve("Centro Norte", ("asset",))
    assert result.status == "ambiguous"
    assert [candidate.entity_key for candidate in result.candidates] == ["north-a", "north-b"]
    assert EntityResolver(DB).resolve("Parque Titanium", ("asset",)).status == "low_confidence"


def test_scripted_resolve_entity_propagates_canonical_asset_to_analytics():
    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("resolve", "resolve_entity", {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None})]),
                ModelResponse("", [ToolRequest("analytics", "analytics_lookup_asset", {"metric": "vacancia_fisica_pct_activo", "assets": ["Apo3001"], "period": "2026-06", "period_end": None})]),
                ModelResponse("respuesta"),
            ])
        def complete(self, _request): return next(self.responses)
    registry = ActionRegistry([ResolveEntityAction(DB), AnalyticsLookupAssetAction(DB)])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")
    assert [call.name for call in result.turn.tool_calls] == ["resolve_entity", "analytics_lookup_asset"]
    assert result.turn.tool_calls[1].args["assets"] == ["Apo3001"]
    payload = json.loads(result.round_trajectory[-2].tool_results[0].content)
    assert payload["rows"][0]["value"] == 0.3620316883059285


def test_canonical_fund_context_filters_asset_candidates():
    result = EntityResolver(DB).resolve("Apoquindo 3001", ("asset",), fund="TRI")
    assert result.status == "resolved"
    assert result.candidates[0].entity_key == "Apo3001"


def test_resolve_entity_action_reports_unexpected_db_error(tmp_path: Path):
    action = ResolveEntityAction(tmp_path / "missing.sqlite")
    result = action.execute(ToolRequest("resolve", action.name, {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None}))
    assert not result.ok
    assert json.loads(result.content)["error_type"] == "resolve_entity_error"
