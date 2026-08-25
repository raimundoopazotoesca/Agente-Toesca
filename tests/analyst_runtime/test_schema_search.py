from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.analyst_runtime.actions import ActionRegistry, AnalyticsDatasetQueryAction, RunSqlAction, SchemaSearchAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ModelResponse, ToolRequest
from tools.datasets.catalog import load_dataset_catalog
from tools.schema_discovery import SQLiteSchemaIntrospector


DB = Path("memory/agente_toesca_v2.db")


def test_schema_search_finds_rent_roll_with_verified_columns_and_relation():
    result = SQLiteSchemaIntrospector(DB).search("rent roll vacancy asset period", limit=5)

    rent_roll = next(obj for obj in result.objects if obj.name == "raw_rent_roll_line")
    assert result.dialect == "sqlite"
    assert result.metadata_version == "sqlite_schema_v1"
    assert rent_roll.source_category == "raw"
    assert {column.name for column in rent_roll.columns} >= {
        "activo_key", "periodo", "unidad", "arrendatario", "m2", "renta_uf", "superseded_at",
    }
    assert any(
        relation.column == "activo_key"
        and relation.target_object == "dim_activo"
        and relation.target_column == "activo_key"
        for relation in rent_roll.relationships
    )


def test_schema_search_is_read_only_deterministic_limited_and_returns_no_match(tmp_path: Path):
    db_path = tmp_path / "schema.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE raw_rent_roll_line (activo_key TEXT, periodo TEXT)")
    conn.execute("CREATE TABLE dim_activo (activo_key TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE other_table (unrelated TEXT)")
    conn.commit()
    conn.close()
    before = db_path.read_bytes()

    introspector = SQLiteSchemaIntrospector(db_path)
    first = introspector.search("rent roll period", limit=99)
    second = introspector.search("rent roll period", limit=99)

    assert [obj.name for obj in first.objects] == [obj.name for obj in second.objects]
    assert len(first.objects) <= 10
    assert first.objects[0].relationships == ()
    assert introspector.search("not-a-real-object", limit=5).objects == ()
    assert db_path.read_bytes() == before


def test_schema_search_action_serializes_metadata_and_trace():
    action = SchemaSearchAction(DB)
    spec = action.tool_spec()
    result = action.execute(ToolRequest("call", action.name, {
        "query": "rent roll vacancy asset period", "limit": 99,
    }))

    payload = json.loads(result.content)
    assert spec.name == "schema_search"
    assert spec.parameters == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {"type": "string", "description": "Metadata search terms for tables, views, columns, and verified relationships."},
            "limit": {"type": ["integer", "null"], "minimum": 1, "description": "Maximum metadata objects returned; use null for the default."},
        },
        "required": ["query", "limit"],
    }
    assert result.ok is True
    assert payload["dialect"] == "sqlite"
    assert any(obj["name"] == "raw_rent_roll_line" for obj in payload["objects"])
    assert result.trace["tool_name"] == "schema_search"
    assert result.trace["requested_limit"] == 99
    assert result.trace["effective_limit"] == 10
    assert "raw_rent_roll_line" in result.trace["candidate_names"]
    assert result.trace["success"] is True
    assert result.trace["duration_ms"] >= 0
    assert result.trace["candidate_scores"]


def test_schema_search_action_rejects_invalid_request_with_typed_trace():
    result = SchemaSearchAction(DB).execute(ToolRequest("call", "schema_search", {
        "query": "rent roll", "limit": 0,
    }))

    assert result.ok is False
    assert json.loads(result.content)["error_type"] == "invalid_request"
    assert result.trace["success"] is False
    assert result.trace["error"]["error_type"] == "invalid_request"


def test_scripted_loop_can_discover_schema_then_run_focal_sql_without_provider():
    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("schema", "schema_search", {
                    "query": "Apoquindo 3001 espacios pisos vacantes junio 2026", "limit": 10,
                })]),
                ModelResponse("", [ToolRequest("dataset", "analytics_query_dataset", {
                    "dataset": "rent_roll", "filters": [{"field": "activo_key", "op": "eq", "value": "Apo3001", "value_end": None}, {"field": "periodo", "op": "eq", "value": "2026-06", "value_end": None}, {"field": "occupancy_status", "op": "eq", "value": "vacant", "value_end": None}], "group_by": ["unidad"], "measures": [{"measure": "gla_m2", "aggregation": "sum"}], "order_by": "gla_m2", "descending": True, "limit": None, "share_of_total": False, "row_axis": None, "column_axis": None,
                })]),
                ModelResponse("respuesta"),
            ])

        def complete(self, _request):
            return next(self.responses)

    registry = ActionRegistry([
        AnalyticsDatasetQueryAction(DB),
        SchemaSearchAction(DB),
    ])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")

    assert [(call.name, call.ok) for call in result.turn.tool_calls] == [
        ("schema_search", True), ("analytics_query_dataset", True),
    ]
    # The real Stage 3.17 wording must expose the governed row-level dataset.
    candidate_names = result.turn.tool_calls[0].trace["candidate_names"]
    assert "raw_rent_roll_line" in candidate_names
    assert result.turn.tool_calls[0].trace["candidate_scores"]["raw_rent_roll_line"] > 0
    schema_result = next(
        tool_result
        for round_ in result.round_trajectory
        for tool_result in round_.tool_results
        if tool_result.call_id == "schema"
    )
    schema_payload = json.loads(schema_result.content)
    semantic = next(obj for obj in schema_payload["objects"] if obj["name"] == "raw_rent_roll_line")
    assert semantic["dataset"]["dataset_key"] == "rent_roll"
    assert semantic["dataset"]["semantic_version"] == "rent_roll_semantics_v1"
    assert {"occupancy_status", "unit_category", "is_current"} <= set(semantic["dataset"]["fields"])
    assert result.turn.usage.calls == 3


def test_schema_search_ranks_governed_row_level_dataset_from_generic_space_metadata():
    result = SQLiteSchemaIntrospector(DB).search(
        "Apoquindo 3001 espacios pisos vacantes junio 2026", limit=10
    )

    names = [obj.name for obj in result.objects]
    assert "raw_rent_roll_line" in names
    assert result.candidate_scores["raw_rent_roll_line"] > 0


def test_schema_search_retrieval_set_keeps_aggregate_breakdown_row_and_raw_candidates():
    introspector = SQLiteSchemaIntrospector(DB)
    cases = {
        "vacancia por activo mensual": "v_vacancia_activo",
        "vacancia por tipo de unidad de un activo": "v_vacancia_activo_tipo",
        "unidades espacios vacantes activo periodo": "raw_rent_roll_line",
        "rent roll archivo fuente fila provenance": "raw_rent_roll_line",
        "movimientos de contrato por activo": "raw_movimiento_contrato",
    }

    for query, expected in cases.items():
        assert expected in [obj.name for obj in introspector.search(query, limit=10).objects]


def test_schema_search_does_not_repeat_generic_dimension_evidence_across_metadata_sources():
    result = SQLiteSchemaIntrospector(DB).search("movimientos de contrato por activo", limit=10)

    assert result.objects[0].name == "raw_movimiento_contrato"


def test_benchmark_contract_exposes_only_frozen_run_sql_tool():
    from eval.benchmark.adapters.track_b_frontier import _RUN_SQL_SPEC

    assert {_RUN_SQL_SPEC.name} == {"run_sql"}
