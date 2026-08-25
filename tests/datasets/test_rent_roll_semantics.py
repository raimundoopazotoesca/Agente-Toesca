from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from tools.datasets.catalog import CATALOG_PATH, DatasetCatalogValidationError, load_dataset_catalog
from tools.analyst_runtime.actions import ActionRegistry, AnalyticsDatasetQueryAction, ResolveEntityAction, RunSqlAction, SchemaSearchAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ModelResponse, ToolRequest
from tools.db import connection as db_connection
from tools.db.connection import apply_migrations, get_conn_for


DB = Path("memory/agente_toesca_v2.db")
MIGRATION = Path("tools/db/migrations/083_governed_rent_roll_dataset.sql")
MIGRATIONS_DIR = Path("tools/db/migrations")


def test_pre_083_fixture_starts_without_the_governed_view(tmp_path: Path, monkeypatch):
    db_path = _pre_083_db(tmp_path, monkeypatch)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_rent_roll_semantic'"
        ).fetchone() is None
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 82
    finally:
        conn.close()


def _pre_083_db(tmp_path: Path, monkeypatch) -> Path:
    """Create the deterministic schema-82 fixture and its minimum golden data."""
    migration_dir = tmp_path / "migrations-through-082"
    migration_dir.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if int(path.stem.split("_", 1)[0]) <= 82:
            shutil.copy2(path, migration_dir / path.name)

    db_path = tmp_path / "knowledge-v82.db"
    monkeypatch.setattr(db_connection, "MIGRATIONS_DIR", migration_dir)
    assert apply_migrations(str(db_path)) == list(range(1, 83))

    conn = get_conn_for(str(db_path))
    try:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_rent_roll_semantic'"
        ).fetchone() is None
        conn.execute("INSERT OR IGNORE INTO dim_fondo(fondo_key, nombre) VALUES ('TRI', 'TRI')")
        conn.executemany(
            "INSERT OR IGNORE INTO dim_activo(activo_key, fondo_key, nombre) VALUES (?, 'TRI', ?)",
            [("Apo3001", "Apo3001"), ("Residencia Arturo Medina", "Residencia Arturo Medina")],
        )

        def row(activo, unidad, arrendatario, m2, categoria, source_row, superseded_at=None):
            return (
                activo, "2026-06", unidad, arrendatario, m2, None,
                json.dumps({"tipo_activo_2": categoria}), "fixture.xlsx", "Rent Roll",
                source_row, "fixture-083", superseded_at,
            )

        vacancies = [
            row("Apo3001", f"Piso {index}", "Vacante", m2, "Oficina", index)
            for index, m2 in enumerate((440.3, 440.3, 234.0, 234.0, 234.0), start=1)
        ]
        vacancies.extend(
            row("Apo3001", f"Zócalo {index}", "Vacante", 8.0, "Estacionamiento", index)
            for index in range(6, 9)
        )
        vacancies.extend(
            row("Apo3001", f"Bodega {index}", "Vacante", 25.0, "Bodega", index)
            for index in range(9, 11)
        )
        occupied = [
            row("Apo3001", f"Oficina ocupada {index}", "Tenant", 100.0, "Oficina", index)
            for index in range(11, 26)
        ]
        history = [
            row("Residencia Arturo Medina", "Unidad 1", "Tenant", 1.0, "Oficina", 101, "2026-06-30"),
            row("Residencia Arturo Medina", "Unidad 1", "Tenant", 1.0, "Oficina", 102),
        ]
        conn.executemany(
            """
            INSERT INTO raw_rent_roll_line(
                activo_key, periodo, unidad, arrendatario, m2, renta_uf, extra_json,
                source_file, source_sheet, source_row, file_hash, superseded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            vacancies + occupied + history,
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _semantic_copy(tmp_path: Path, monkeypatch) -> sqlite3.Connection:
    """Apply 083 in isolation (migrations through 083 only) to a reproducible v82 fixture.

    Capped below 084 on purpose: this fixture exercises the 083 governed rent-roll
    dataset migration specifically, not the unrelated 084 vacancy/parking normalization.
    """
    db_path = _pre_083_db(tmp_path, monkeypatch)
    migration_dir_083 = tmp_path / "migrations-through-083"
    migration_dir_083.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if int(path.stem.split("_", 1)[0]) <= 83:
            shutil.copy2(path, migration_dir_083 / path.name)
    monkeypatch.setattr(db_connection, "MIGRATIONS_DIR", migration_dir_083)
    assert apply_migrations(str(db_path)) == [83]
    conn = get_conn_for(str(db_path))
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 83
    return conn


def test_dataset_catalog_declares_the_row_level_rent_roll_contract_with_closed_value_domains():
    catalog = load_dataset_catalog()
    dataset = catalog.datasets["rent_roll"]

    assert catalog.version == 1
    assert dataset.dataset_key == "rent_roll"
    assert dataset.semantic_version == "rent_roll_semantics_v1"
    assert dataset.object_name == "raw_rent_roll_line"
    assert dataset.grain == "rent_roll_row"
    assert set(dataset.semantic_fields) == {
        "occupancy_status", "unit_category", "unit_category_source",
        "unit_identity_quality", "tenant_type", "vencimiento", "expiry_year", "is_current",
    }
    assert {"source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id"} <= set(dataset.provenance_fields)
    assert dataset.field_value_domains == {
        "occupancy_status": {"type": "enum", "values": ("vacant", "occupied", "unknown")},
        "unit_category": {"type": "enum", "values": ("office", "local", "storage", "parking", "other_source_declared", "unknown")},
        "unit_identity_quality": {"type": "enum", "values": ("source_identity", "synthetic_missing_source_identity")},
        "is_current": {"type": "boolean", "values": (0, 1)},
    }
    assert "unit_category_source" not in dataset.field_value_domains


def test_dataset_catalog_serializes_declarative_row_semantics_and_field_descriptions():
    dataset = load_dataset_catalog().datasets["rent_roll"]

    assert dataset.grain_description == (
        "Fila individual de rent roll correspondiente a una unidad o espacio fuente para un activo y período."
    )
    assert dataset.row_represents == "Unidad o espacio individual reportado por la fuente del rent roll."
    assert dataset.field_descriptions["unidad"] == (
        "Identificador o etiqueta de la unidad o espacio reportado por la fuente."
    )
    assert dataset.schema_metadata()["dimensions"] == ["activo_key", "periodo"]
    assert dataset.schema_metadata()["fields"]["occupancy_status"] == (
        "Estado de ocupación gobernado de la fila, como vacante, ocupada o desconocida."
    )


def test_value_domain_catalog_validation_is_generic_and_fail_fast(tmp_path: Path):
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    definition = raw["datasets"][0]
    definition["fields"].append("field_x")
    definition["field_descriptions"]["field_x"] = "Campo temporal con dominio cerrado."
    definition["field_value_domains"] = {"field_x": {"type": "enum", "values": ["a", "b"]}}
    valid = tmp_path / "valid.yaml"
    valid.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert load_dataset_catalog(valid).datasets["rent_roll"].schema_metadata()["field_value_domains"]["field_x"] == {
        "type": "enum", "values": ["a", "b"],
    }

    invalid_cases = {
        "unknown-field": {"missing": {"type": "enum", "values": ["a"]}},
        "empty-enum": {"field_x": {"type": "enum", "values": []}},
        "duplicate-values": {"field_x": {"type": "enum", "values": ["a", "a"]}},
        "bad-type": {"field_x": {"type": "free_text", "values": ["a"]}},
    }
    for label, domain in invalid_cases.items():
        definition["field_value_domains"] = domain
        path = tmp_path / f"{label}.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        with pytest.raises(DatasetCatalogValidationError):
            load_dataset_catalog(path)


def test_semantic_view_keeps_history_and_marks_currentness(tmp_path: Path, monkeypatch):
    """Previously copied the real v83 DB; the fixture now starts at v82."""
    conn = _semantic_copy(tmp_path, monkeypatch)
    try:
        rows = conn.execute(
            "SELECT is_current FROM v_rent_roll_semantic WHERE activo_key='Residencia Arturo Medina' AND periodo='2026-06'"
        ).fetchall()
    finally:
        conn.close()

    assert sorted(row[0] for row in rows) == [0, 1]


def test_golden_apo3001_june_keeps_all_raw_vacancy_and_kpi_remains_distinct(tmp_path: Path, monkeypatch):
    """Previously copied the real v83 DB; golden rows are now test-owned at v82."""
    conn = _semantic_copy(tmp_path, monkeypatch)
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


def test_schema_search_discovers_the_governed_dataset_with_declarative_contract(tmp_path: Path, monkeypatch):
    """Previously copied the real v83 DB; discovery now validates one v82→v83 run."""
    conn = _semantic_copy(tmp_path, monkeypatch)
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.close()

    result = SchemaSearchAction(db_path).execute(ToolRequest("call", "schema_search", {
        "query": "rent roll vacancy asset period", "limit": 5,
    }))
    payload = json.loads(result.content)
    semantic = next(obj for obj in payload["objects"] if obj["name"] == "raw_rent_roll_line")

    assert result.ok is True
    assert payload["objects"][0]["name"] == "raw_rent_roll_line"
    assert {
        "dataset_key": "rent_roll", "semantic_version": "rent_roll_semantics_v1",
        "grain": "rent_roll_row", "description": semantic["description"],
        "grain_description": "Fila individual de rent roll correspondiente a una unidad o espacio fuente para un activo y período.",
        "row_represents": "Unidad o espacio individual reportado por la fuente del rent roll.",
        "dimensions": ["activo_key", "periodo"],
        "status": "active",
    }.items() <= semantic["dataset"].items()
    assert semantic["dataset"]["fields"]["unidad"] == (
        "Identificador o etiqueta de la unidad o espacio reportado por la fuente."
    )
    assert semantic["dataset"]["field_value_domains"]["occupancy_status"] == {
        "type": "enum", "values": ["vacant", "occupied", "unknown"],
    }
    assert {"occupancy_status", "unit_category", "is_current"} <= set(semantic["dataset"]["fields"])


def test_scripted_schema_search_then_run_sql_uses_governed_rent_roll_dataset(tmp_path: Path, monkeypatch):
    """Previously copied the real v83 DB; scripted wiring now uses the isolated migration."""
    conn = _semantic_copy(tmp_path, monkeypatch)
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.close()

    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("schema", "schema_search", {"query": "rent roll vacancy asset period", "limit": 5})]),
                ModelResponse("", [ToolRequest("dataset", "analytics_query_dataset", {"dataset": "rent_roll", "filters": [{"field": "activo_key", "op": "eq", "value": "Apo3001", "value_end": None}, {"field": "periodo", "op": "eq", "value": "2026-06", "value_end": None}, {"field": "occupancy_status", "op": "eq", "value": "vacant", "value_end": None}], "group_by": ["unidad", "unit_category"], "measures": [{"measure": "gla_m2", "aggregation": "sum"}], "order_by": "gla_m2", "descending": True, "limit": None, "share_of_total": False, "row_axis": None, "column_axis": None})]),
                ModelResponse("respuesta"),
            ])

        def complete(self, _request):
            return next(self.responses)

    registry = ActionRegistry([SchemaSearchAction(db_path), AnalyticsDatasetQueryAction(db_path)])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")
    rows = json.loads(result.round_trajectory[-2].tool_results[0].content)["rows"]

    assert [(call.name, call.ok) for call in result.turn.tool_calls] == [("schema_search", True), ("analytics_query_dataset", True)]
    assert len(rows) == 10
    assert sum(row["gla_m2"] for row in rows) == pytest.approx(1656.6)


def test_scripted_m3_uses_visible_canonical_value_domain(tmp_path: Path, monkeypatch):
    conn = _semantic_copy(tmp_path, monkeypatch)
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.close()

    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("resolve", "resolve_entity", {"query": "Apoquindo 3001", "entity_types": ["asset"], "fund": None})]),
                ModelResponse("", [ToolRequest("schema", "schema_search", {"query": "Apoquindo 3001 espacios pisos vacantes junio 2026", "limit": 10})]),
                ModelResponse("", [ToolRequest("dataset", "analytics_query_dataset", {"dataset": "rent_roll", "filters": [{"field": "activo_key", "op": "eq", "value": "Apo3001", "value_end": None}, {"field": "periodo", "op": "eq", "value": "2026-06", "value_end": None}, {"field": "occupancy_status", "op": "eq", "value": "vacant", "value_end": None}], "group_by": ["unidad"], "measures": [{"measure": "gla_m2", "aggregation": "sum"}], "order_by": "gla_m2", "descending": True, "limit": None, "share_of_total": False, "row_axis": None, "column_axis": None})]),
                ModelResponse("respuesta"),
            ])

        def complete(self, _request):
            return next(self.responses)

    registry = ActionRegistry([ResolveEntityAction(db_path), SchemaSearchAction(db_path), AnalyticsDatasetQueryAction(db_path)])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")
    schema_payload = json.loads(result.round_trajectory[-3].tool_results[0].content)
    semantic = next(obj for obj in schema_payload["objects"] if obj["name"] == "raw_rent_roll_line")
    rows = json.loads(result.round_trajectory[-2].tool_results[0].content)["rows"]

    assert [call.name for call in result.turn.tool_calls] == ["resolve_entity", "schema_search", "analytics_query_dataset"]
    assert result.turn.tool_calls[-1].args["filters"][-1]["value"] == "vacant"
    assert semantic["dataset"]["field_value_domains"]["occupancy_status"]["values"] == ["vacant", "occupied", "unknown"]
    assert len(rows) == 10
    assert sum(row["gla_m2"] for row in rows) == pytest.approx(1656.6)
