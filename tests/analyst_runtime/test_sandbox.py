"""Stage A2: the live read-only SqlSandbox contract.

Normal tests use temporary SQLite fixtures exclusively.  The optional live
database smoke test is deliberately opt-in so the protected production DB is
never a dependency of the regular test suite.
"""
from __future__ import annotations

import json

import os
import sqlite3
from pathlib import Path

import pytest

from tools.analyst_runtime.actions import AnalyticsLookupFundAction, RunSqlAction, validate_sql
from tools.analyst_runtime.transport import ToolRequest
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ToolRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DB = REPO_ROOT / "memory" / "agente_toesca_v2.db"


def _make_fixture_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT PRIMARY KEY, nombre TEXT)")
    conn.execute("INSERT INTO dim_fondo VALUES ('PT', 'Parque Titanium')")
    conn.execute("INSERT INTO dim_fondo VALUES ('TRI', 'Rentas TRI')")
    conn.commit()
    conn.close()


@pytest.fixture
def fixture_db(tmp_path) -> Path:
    path = tmp_path / "fixture.db"
    _make_fixture_db(path)
    return path


# ---------------------------------------------------------------------------
# validate_sql
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql", ["SELECT 1", "select * from dim_fondo", "WITH x AS (SELECT 1) SELECT * FROM x"])
def test_validate_sql_allows_select_and_with(sql):
    assert validate_sql(sql) is None


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO dim_fondo VALUES ('X','Y')",
        "UPDATE dim_fondo SET nombre='x'",
        "DELETE FROM dim_fondo",
        "CREATE TABLE x (a int)",
        "DROP TABLE dim_fondo",
        "PRAGMA table_info(dim_fondo)",
        "ATTACH DATABASE 'x.db' AS x",
        "SELECT 1; SELECT 2",
    ],
)
def test_validate_sql_rejects_writes_and_multi_statement(sql):
    assert validate_sql(sql) is not None


# ---------------------------------------------------------------------------
# LiveReadOnlySandbox: authorizer enforcement (temp-file only)
# ---------------------------------------------------------------------------

def test_live_sandbox_select_allowed(fixture_db):
    sandbox = LiveReadOnlySandbox(fixture_db)
    conn = sandbox.connect(guard=True)
    try:
        rows = conn.execute("SELECT fondo_key FROM dim_fondo ORDER BY fondo_key").fetchall()
        assert rows == [("PT",), ("TRI",)]
    finally:
        conn.close()


def test_live_sandbox_authorizer_denies_write(fixture_db):
    sandbox = LiveReadOnlySandbox(fixture_db)
    conn = sandbox.connect(guard=True)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO dim_fondo VALUES ('X','Y')")
    finally:
        conn.close()


def test_live_sandbox_mode_ro_denies_write_without_authorizer(fixture_db):
    sandbox = LiveReadOnlySandbox(fixture_db)
    conn = sandbox.connect(guard=False)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO dim_fondo VALUES ('X','Y')")
    finally:
        conn.close()


def test_live_sandbox_can_close_connection_normally(fixture_db):
    conn = LiveReadOnlySandbox(fixture_db).connect()
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_live_sandbox_missing_database_path_is_clear(tmp_path):
    missing_path = tmp_path / "missing.db"
    sandbox = LiveReadOnlySandbox(missing_path)
    with pytest.raises(FileNotFoundError, match="does not exist"):
        sandbox.connect()


def test_live_sandbox_never_writes_to_disk(fixture_db):
    before = os.stat(fixture_db)
    sandbox = LiveReadOnlySandbox(fixture_db)
    conn = sandbox.connect(guard=True)
    conn.execute("SELECT 1").fetchall()
    conn.close()
    after = os.stat(fixture_db)
    assert before.st_mtime == after.st_mtime
    assert before.st_size == after.st_size


# ---------------------------------------------------------------------------
# RunSqlAction: identical shape via SnapshotSandbox vs LiveReadOnlySandbox
# ---------------------------------------------------------------------------

def test_run_sql_action_same_shape_via_live_sandbox(fixture_db):
    sandbox = LiveReadOnlySandbox(fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT fondo_key FROM dim_fondo ORDER BY fondo_key"}))
    assert result.ok is True
    assert '"columns"' in result.content
    assert '"PT"' in result.content


def test_run_sql_action_same_shape_via_snapshot_sandbox(fixture_db):
    from eval.benchmark.snapshot import SnapshotSandbox

    # SnapshotSandbox.__init__ normally materializes the pinned benchmark
    # snapshot; here we bypass that and point it directly at our own fixture
    # to compare RunSqlAction's output shape against LiveReadOnlySandbox's,
    # without touching the real pinned snapshot or the real production DB.
    sandbox = SnapshotSandbox.__new__(SnapshotSandbox)
    sandbox.path = fixture_db
    from eval.benchmark.snapshot import QueryLog

    sandbox.log = QueryLog()
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT fondo_key FROM dim_fondo ORDER BY fondo_key"}))
    assert result.ok is True
    assert '"columns"' in result.content
    assert '"PT"' in result.content


def test_run_sql_action_rejects_write_same_error_shape(fixture_db):
    sandbox = LiveReadOnlySandbox(fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "DELETE FROM dim_fondo"}))
    assert result.ok is False
    assert "error" in result.content


# ---------------------------------------------------------------------------
# ONE non-destructive smoke test against the real production DB.
# ---------------------------------------------------------------------------

@pytest.mark.live_db_smoke
@pytest.mark.skipif(
    os.getenv("TOESCA_RUN_LIVE_DB_SMOKE") != "1",
    reason="set TOESCA_RUN_LIVE_DB_SMOKE=1 to run against the protected live DB",
)
@pytest.mark.skipif(not REAL_DB.exists(), reason="memory/agente_toesca_v2.db not present")
def test_live_sandbox_against_real_db_is_read_only_and_untouched():
    before = os.stat(REAL_DB)
    sandbox = LiveReadOnlySandbox(REAL_DB)
    conn = sandbox.connect(guard=True)
    try:
        row = conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        assert row is not None
    finally:
        conn.close()
    after = os.stat(REAL_DB)
    assert before.st_mtime == after.st_mtime
    assert before.st_size == after.st_size

def test_analytics_lookup_fund_action_returns_semantic_envelope_for_canonical_lookup():
    action = AnalyticsLookupFundAction(db_path=REAL_DB)
    result = action.execute(ToolRequest("1", "analytics_lookup_fund", {"metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06"}))
    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["catalog_version"] == 1
    assert payload["rows"][0]["metric_key"] == "vacancia_pct_fondo"
    assert payload["rows"][0]["source_kind"] == "canonical"
