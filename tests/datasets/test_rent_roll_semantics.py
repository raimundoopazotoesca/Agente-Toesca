from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tools.datasets.catalog import load_dataset_catalog
from tools.analyst_runtime.actions import ActionRegistry, RunSqlAction, SchemaSearchAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ModelResponse, ToolRequest


DB = Path("memory/agente_toesca_v2.db")
MIGRATION = Path("tools/db/migrations/083_governed_rent_roll_dataset.sql")


def _semantic_copy(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "knowledge-copy.db"
    shutil.copy2(DB, db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return conn


def test_dataset_catalog_declares_the_row_level_rent_roll_contract_without_values():
    catalog = load_dataset_catalog()
    dataset = catalog.datasets["rent_roll"]

    assert catalog.version == 1
    assert dataset.dataset_key == "rent_roll"
    assert dataset.semantic_version == "rent_roll_semantics_v1"
    assert dataset.object_name == "v_rent_roll_semantic"
    assert dataset.grain == "rent_roll_row"
    assert set(dataset.semantic_fields) == {
        "occupancy_status", "unit_category", "unit_category_source",
        "unit_identity_quality", "is_current",
    }
    assert {"source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id"} <= set(dataset.provenance_fields)
    assert "1656.6" not in repr(catalog.as_dict())


def test_semantic_view_keeps_history_and_marks_currentness(tmp_path: Path):
    conn = _semantic_copy(tmp_path)
    try:
        rows = conn.execute(
            "SELECT is_current FROM v_rent_roll_semantic WHERE activo_key='Residencia Arturo Medina' AND periodo='2026-06'"
        ).fetchall()
    finally:
        conn.close()

    assert sorted(row[0] for row in rows) == [0, 1]


def test_golden_apo3001_june_keeps_all_raw_vacancy_and_kpi_remains_distinct(tmp_path: Path):
    conn = _semantic_copy(tmp_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM v_rent_roll_semantic WHERE activo_key='Apo3001' AND periodo='2026-06' AND is_current=1"
        ).fetchone()[0]
        by_status = dict(conn.execute(
            "SELECT occupancy_status, COUNT(*) FROM v_rent_roll_semantic WHERE activo_key='Apo3001' AND periodo='2026-06' AND is_current=1 GROUP BY occupancy_status"
        ).fetchall())
        by_category = dict(conn.execute(
            "SELECT unit_category, SUM(m2) FROM v_rent_roll_semantic WHERE activo_key='Apo3001' AND periodo='2026-06' AND is_current=1 AND occupancy_status='vacant' GROUP BY unit_category"
        ).fetchall())
        governed = conn.execute(
            "SELECT m2_vacantes FROM v_vacancia_activo WHERE activo_key='Apo3001' AND periodo='2026-06'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert total == 25
    assert by_status == {"occupied": 15, "vacant": 10}
    assert by_category == {"office": pytest.approx(1582.6), "parking": pytest.approx(24.0), "storage": pytest.approx(50.0)}
    assert sum(by_category.values()) == pytest.approx(1656.6)
    assert governed == pytest.approx(1632.6)
    assert sum(by_category.values()) - by_category["parking"] == pytest.approx(governed)


def test_semantic_view_classifies_frozen_occupancy_and_category_edges(tmp_path: Path):
    db_path = tmp_path / "edges.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE raw_rent_roll_line (
          activo_key TEXT, periodo TEXT, unidad TEXT, arrendatario TEXT, m2 REAL, renta_uf REAL,
          extra_json TEXT, source_file TEXT, source_sheet TEXT, source_row INTEGER, file_hash TEXT,
          ingest_run_id INTEGER, superseded_at TEXT
        );
    """)
    values = [
        ("Vacante", "Oficina", "Piso 1", None), ("vacante", "Local", "Piso 2", None),
        (" Vacante ", "Bodega", "Piso 3", 0.5), (None, None, "Piso 4", None),
        ("", None, "Piso 5", None), ("   ", None, "Piso 6", None),
        ("Vacante temporal", "Parking", "Piso 7", None), ("Tenant", "Módulo", "Piso 8", None),
        ("Vacante", "Estacionamiento", "(sin detalle, fila 8)", None), ("Tenant", "Oficina", "Piso 9", None),
    ]
    conn.executemany(
        "INSERT INTO raw_rent_roll_line VALUES ('A','2026-06',?,?,100,?,?,'source','sheet',1,'hash',7,?)",
        [(unidad, tenant, renta, json.dumps({"tipo_activo_2": category}), superseded) for tenant, category, unidad, renta, superseded in [(*row, None) for row in values]],
    )
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    rows = conn.execute(
        "SELECT unidad, occupancy_status, unit_category, unit_identity_quality FROM v_rent_roll_semantic ORDER BY unidad"
    ).fetchall()
    conn.close()

    observed = {row[0]: row[1:] for row in rows}
    assert observed["Piso 1"] == ("vacant", "office", "source_identity")
    assert observed["Piso 2"] == ("vacant", "local", "source_identity")
    assert observed["Piso 3"] == ("vacant", "storage", "source_identity")
    assert observed["Piso 4"][0] == observed["Piso 5"][0] == observed["Piso 6"][0] == "unknown"
    assert observed["Piso 7"] == ("unknown", "parking", "source_identity")
    assert observed["Piso 8"] == ("occupied", "other_source_declared", "source_identity")
    assert observed["(sin detalle, fila 8)"] == ("vacant", "parking", "synthetic_missing_source_identity")


def test_schema_search_discovers_the_governed_dataset_with_declarative_contract(tmp_path: Path):
    conn = _semantic_copy(tmp_path)
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.close()

    result = SchemaSearchAction(db_path).execute(ToolRequest("call", "schema_search", {
        "query": "rent roll vacancy asset period", "limit": 5,
    }))
    payload = json.loads(result.content)
    semantic = next(obj for obj in payload["objects"] if obj["name"] == "v_rent_roll_semantic")

    assert result.ok is True
    assert payload["objects"][0]["name"] == "v_rent_roll_semantic"
    assert semantic["dataset"] == {
        "dataset_key": "rent_roll", "semantic_version": "rent_roll_semantics_v1",
        "grain": "rent_roll_row", "description": semantic["description"],
        "semantic_fields": ["occupancy_status", "unit_category", "unit_category_source", "unit_identity_quality", "is_current"],
        "provenance_fields": ["source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id"],
        "status": "active",
    }
    assert {"occupancy_status", "unit_category", "is_current"} <= {column["name"] for column in semantic["columns"]}


def test_scripted_schema_search_then_run_sql_uses_governed_rent_roll_dataset(tmp_path: Path):
    conn = _semantic_copy(tmp_path)
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.close()

    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("schema", "schema_search", {"query": "rent roll vacancy asset period", "limit": 5})]),
                ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT unidad, m2, unit_category FROM v_rent_roll_semantic WHERE activo_key='Apo3001' AND periodo='2026-06' AND is_current=1 AND occupancy_status='vacant' ORDER BY source_row"})]),
                ModelResponse("respuesta"),
            ])

        def complete(self, _request):
            return next(self.responses)

    registry = ActionRegistry([SchemaSearchAction(db_path), RunSqlAction(LiveReadOnlySandbox(db_path))])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")
    rows = json.loads(result.round_trajectory[-2].tool_results[0].content)["rows"]

    assert [(call.name, call.ok) for call in result.turn.tool_calls] == [("schema_search", True), ("run_sql", True)]
    assert len(rows) == 10
    assert sum(row[1] for row in rows) == pytest.approx(1656.6)
