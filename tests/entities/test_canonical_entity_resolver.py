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


def test_resolve_entity_action_serializes_safe_trace_and_m3_key_propagates(governed_v84_db):
    """Owns the exact golden-value pin (row_count==10, sum(m2)==1656.6) for
    this Apo3001/2026-06 vacant-units query: this test is specifically about
    the resolved key ("Apoquindo 3001" -> "Apo3001") propagating into a real
    downstream schema_search/run_sql call and producing the *correct*
    governed result, not just a non-error one.

    Uses a deterministic schema-84 fixture (tests/conftest.py::governed_v84_db)
    instead of the tracked memory/agente_toesca_v2.db so this doesn't depend
    on that file's schema version at test time. See
    tests/analyst_runtime/test_entity_resolution_barrier.py::
    test_resolved_entity_keeps_m3_and_analytics_paths_open for the sibling
    test that asserts only the lighter structural condition (the barrier
    does not block a resolved entity) on the same fixture, to avoid pinning
    the identical exact values twice.
    """
    action = ResolveEntityAction(governed_v84_db)
    result = action.execute(ToolRequest("resolve", action.name, {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None}))
    payload = json.loads(result.content)
    assert result.ok and payload["candidates"][0]["entity_key"] == "Apo3001"
    assert result.trace["status"] == "resolved"
    assert result.trace["resolution"]["status"] == "resolved"
    assert result.trace["resolution"]["canonical_value"] == "Apo3001"
    assert result.trace["resolution"]["method"] == "exact_display"
    assert result.trace["resolution"]["evidence"]["internal_status"] == "resolved"

    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("resolve", "resolve_entity", {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None})]),
                ModelResponse("", [ToolRequest("schema", "schema_search", {"query": "unidades espacios vacantes activo periodo", "limit": 10})]),
                ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT unidad, m2 FROM v_rent_roll_semantic WHERE activo_key='Apo3001' AND periodo='2026-06' AND is_current=1 AND occupancy_status='vacant'"})]),
                ModelResponse("respuesta"),
            ])
        def complete(self, _request): return next(self.responses)
    registry = ActionRegistry([
        ResolveEntityAction(governed_v84_db),
        SchemaSearchAction(governed_v84_db),
        RunSqlAction(LiveReadOnlySandbox(governed_v84_db)),
    ])
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


@pytest.mark.parametrize("query,entity_types,expected_key", [
    ("TP", ("fund",), "PT"),
    ("apoqundo", ("fund",), "Apo"),
    ("Fóndo Apoquindo", ("fund",), "Apo"),
])
def test_resolver_safely_suggests_or_resolves_reasonable_typed_typos(query, entity_types, expected_key):
    result = EntityResolver(DB).resolve(query, entity_types)
    assert result.candidates[0].entity_key == expected_key
    assert result.status in {"resolved", "low_confidence"}


def test_bare_fund_alias_is_not_spuriously_ambiguous_against_divested_entities():
    """dim_activo/dim_sociedad retain divested entities for history (Machalí,
    divested 2025) whose display names happen to contain "tri" as a raw
    substring ("Strip Machalí"). Querying the fund alias "TRI" across all
    entity types must resolve cleanly -- it must not surface that
    coincidental letter overlap as a competing candidate."""
    result = EntityResolver(DB).resolve("TRI", ("fund", "asset", "company"))
    assert result.status == "resolved"
    assert result.candidates[0].entity_key == "TRI"


@pytest.mark.parametrize("query,serie", [
    ("TRI serie A", "A"),
    ("TRI Serie A", "A"),
    ("serie I de TRI", "I"),
])
def test_fund_serie_compound_expressions_resolve_the_fund(query, serie):
    result = EntityResolver(DB).resolve(query, ("fund", "asset", "company"))
    assert result.status == "resolved"
    assert result.candidates[0].entity_key == "TRI"
    assert result.candidates[0].evidence.get("serie_qualifier") == serie


def test_cross_type_ambiguity_retains_all_candidate_types():
    result = EntityResolver(DB).resolve("Apoquindo", ("fund", "asset"))
    assert result.status == "ambiguous"
    assert {candidate.entity_type for candidate in result.candidates} == {"fund", "asset"}


def test_resolve_entity_action_reports_unexpected_db_error(tmp_path: Path):
    action = ResolveEntityAction(tmp_path / "missing.sqlite")
    result = action.execute(ToolRequest("resolve", action.name, {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None}))
    assert not result.ok
    assert json.loads(result.content)["error_type"] == "resolve_entity_error"
