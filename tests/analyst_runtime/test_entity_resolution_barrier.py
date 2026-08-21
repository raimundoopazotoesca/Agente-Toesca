from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.analyst_runtime.actions import ActionRegistry, AnalyticsLookupAssetAction, ResolveEntityAction, RunSqlAction, SchemaSearchAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession
from tools.analyst_runtime.transport import ModelResponse, ToolRequest, ToolResult, ToolSpec


DB = Path("memory/agente_toesca_v2.db")


class ScriptedTransport:
    def __init__(self, responses: list[ModelResponse]):
        self.responses = iter(responses)
        self.calls = 0

    def complete(self, _request):
        self.calls += 1
        return next(self.responses)


class RecordingAction:
    def __init__(self, name: str):
        self.name = name
        self.calls: list[ToolRequest] = []

    def tool_spec(self):
        return ToolSpec(self.name, self.name, {"type": "object", "properties": {}, "required": []})

    def execute(self, request: ToolRequest):
        self.calls.append(request)
        return ToolResult(request.call_id, True, "{}")


class RecordingPresenter:
    def __init__(self):
        self.calls = 0

    def present(self, **_kwargs):
        self.calls += 1
        raise AssertionError("clarification must not reach the presenter")


def _loop(db_path: Path, transport: ScriptedTransport, *extra):
    registry = ActionRegistry([ResolveEntityAction(db_path), *extra])
    return AnalystLoop("sys", transport, registry, registry.tool_specs())


def test_low_confidence_terminates_before_sql_and_auto_promotion():
    sql = RecordingAction("run_sql")
    transport = ScriptedTransport([
        ModelResponse("", [
            ToolRequest("resolve", "resolve_entity", {"query": "Parque Titanium", "entity_types": ["asset"], "fund": None}),
            ToolRequest("sql", "run_sql", {"query": "SELECT 'Parking PT'"}),
        ]),
        ModelResponse("", [ToolRequest("promote", "resolve_entity", {"query": "Parking Parque Titanium (SABA)", "entity_types": ["asset"], "fund": None})]),
    ])

    result = _loop(DB, transport, sql).ask("consulta")

    assert result.turn.raw["termination_reason"] == "clarification_required"
    assert result.turn.tool_calls[0].trace["resolution_status"] == "low_confidence"
    assert result.turn.tool_calls[0].trace["blocked_followup_tool_calls"] == ["run_sql"]
    assert [call.name for call in result.turn.tool_calls] == ["resolve_entity"]
    assert sql.calls == []
    assert transport.calls == 1
    assert "No pude resolver" in result.turn.text


@pytest.mark.parametrize("query,status", [("activo inexistente", "not_found")])
def test_non_resolved_entity_blocks_analytical_tools(query: str, status: str):
    analytics = RecordingAction("analytics_lookup_asset")
    transport = ScriptedTransport([ModelResponse("", [
        ToolRequest("resolve", "resolve_entity", {"query": query, "entity_types": ["asset"], "fund": None}),
        ToolRequest("analytics", "analytics_lookup_asset", {"asset": "anything"}),
    ])])

    result = _loop(DB, transport, analytics).ask("consulta")

    assert result.turn.raw["termination_reason"] == "clarification_required"
    assert result.turn.tool_calls[0].trace["resolution_status"] == status
    assert analytics.calls == []


def test_ambiguous_entity_blocks_followup_tools(tmp_path: Path):
    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE dim_activo (activo_key TEXT, nombre TEXT, fondo_key TEXT, sociedad_key TEXT, vigente_hasta TEXT)")
    conn.executemany("INSERT INTO dim_activo VALUES (?, ?, 'TRI', NULL, NULL)", [("north-a", "Centro Norte"), ("north-b", "Centro Norte")])
    conn.commit()
    conn.close()
    sql = RecordingAction("run_sql")
    transport = ScriptedTransport([ModelResponse("", [
        ToolRequest("resolve", "resolve_entity", {"query": "Centro Norte", "entity_types": ["asset"], "fund": None}),
        ToolRequest("sql", "run_sql", {"query": "SELECT 1"}),
    ])])

    result = _loop(db_path, transport, sql).ask("consulta")

    assert result.turn.raw["termination_reason"] == "clarification_required"
    assert result.turn.tool_calls[0].trace["resolution_status"] == "ambiguous"
    assert sql.calls == []


def test_resolved_entity_keeps_m3_and_analytics_paths_open():
    class M3Transport(ScriptedTransport):
        def __init__(self):
            super().__init__([
                ModelResponse("", [ToolRequest("resolve", "resolve_entity", {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None})]),
                ModelResponse("", [ToolRequest("schema", "schema_search", {"query": "unidades espacios vacantes activo periodo", "limit": 10})]),
                ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT unidad, m2 FROM v_rent_roll_semantic WHERE activo_key='Apo3001' AND periodo='2026-06' AND is_current=1 AND occupancy_status='vacant'"})]),
                ModelResponse("respuesta"),
            ])

    transport = M3Transport()
    registry = ActionRegistry([ResolveEntityAction(DB), SchemaSearchAction(DB), RunSqlAction(LiveReadOnlySandbox(DB))])
    result = AnalystLoop("sys", transport, registry, registry.tool_specs()).ask("consulta")
    payload = json.loads(result.round_trajectory[-2].tool_results[0].content)

    assert "termination_reason" not in result.turn.raw
    assert [call.name for call in result.turn.tool_calls] == ["resolve_entity", "schema_search", "run_sql"]
    assert payload["row_count"] == 10
    assert sum(row[payload["columns"].index("m2")] for row in payload["rows"]) == pytest.approx(1656.6)


def test_next_user_turn_resets_barrier_and_skips_presenter_for_clarification():
    transport = ScriptedTransport([
        ModelResponse("", [ToolRequest("low", "resolve_entity", {"query": "Parque Titanium", "entity_types": ["asset"], "fund": None})]),
        ModelResponse("", [ToolRequest("resolved", "resolve_entity", {"query": "Parking Parque Titanium (SABA)", "entity_types": ["asset"], "fund": None})]),
        ModelResponse("respuesta", []),
        ModelResponse("respuesta", structured_output={
            "fragments": [{"type": "text", "text": "respuesta"}],
            "canonical_metric_claims": [], "governed_dataset_claims": [],
        }),
    ])
    registry = ActionRegistry([ResolveEntityAction(DB)])
    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", transport, registry, registry.tool_specs()), presenter=None)

    first = session.ask("Parque Titanium")
    second = session.ask("Me refiero al Parking Parque Titanium (SABA)")

    assert first.presentation_integrity_status == "clarification_required"
    assert first.tool_calls[0].trace["clarification_required"] is True
    assert [call.name for call in second.tool_calls] == ["resolve_entity"]
    assert second.tool_calls[0].trace["resolution_status"] == "resolved"


def test_clarification_does_not_invoke_final_presenter():
    transport = ScriptedTransport([ModelResponse("", [ToolRequest("low", "resolve_entity", {"query": "Parque Titanium", "entity_types": ["asset"], "fund": None})])])
    registry = ActionRegistry([ResolveEntityAction(DB)])
    presenter = RecordingPresenter()
    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", transport, registry, registry.tool_specs()), presenter=presenter)

    result = session.ask("Parque Titanium")

    assert result.presentation_integrity_status == "clarification_required"
    assert presenter.calls == 0
