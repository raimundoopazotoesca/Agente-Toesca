import sqlite3

from tools.db import sql_surface
from tools.db.connection import _aplicar_baseline, _ensure_schema_version_table


def _scratch_schema84_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    _ensure_schema_version_table(conn)
    _aplicar_baseline(conn)
    return conn


def test_registry_cardinality():
    assert len(sql_surface.MODEL_QUERYABLE_TABLES) == 44
    assert len(sql_surface.MODEL_QUERYABLE_VIEWS) == 33
    assert len(sql_surface.MODEL_QUERYABLE) == 77
    assert len(sql_surface.INTERNAL) == 2
    assert len(sql_surface.SQLITE_INTERNAL) == 1


def test_bucket_disjointness():
    buckets = [
        sql_surface.MODEL_QUERYABLE_TABLES,
        sql_surface.MODEL_QUERYABLE_VIEWS,
        sql_surface.INTERNAL,
        sql_surface.SQLITE_INTERNAL,
    ]
    seen: set[str] = set()
    for bucket in buckets:
        assert not (bucket & seen), f"overlap found: {bucket & seen}"
        seen |= bucket


def test_deny_by_default_for_unknown_objects():
    assert sql_surface.classify("not_a_real_object") == "UNCLASSIFIED"
    assert sql_surface.is_queryable("not_a_real_object") is False
    assert sql_surface.is_queryable("dim_kpi") is False
    assert sql_surface.is_queryable("schema_version") is False
    assert sql_surface.is_queryable("sqlite_sequence") is False


def test_schema84_drift_against_scratch_baseline():
    conn = _scratch_schema84_conn()
    try:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    names = [name for name, _ in rows]
    non_sqlite = {name for name in names if not name.startswith("sqlite_")}
    tables = {name for name, kind in rows if kind == "table"}
    views = {name for name, kind in rows if kind == "view"}

    assert len(rows) == 80, f"expected 80 total schema84 objects, got {len(rows)}"
    assert len(tables) == 47, f"expected 47 tables (incl. sqlite_sequence), got {len(tables)}"
    assert len(views) == 33, f"expected 33 views, got {len(views)}"

    assert non_sqlite == sql_surface.MODEL_QUERYABLE | sql_surface.INTERNAL
    assert len(non_sqlite) == 79

    assert "sqlite_sequence" in names
    assert "sqlite_sequence" not in non_sqlite

    unclassified = [name for name in non_sqlite if sql_surface.classify(name) == "UNCLASSIFIED"]
    assert unclassified == []
