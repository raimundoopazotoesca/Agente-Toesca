"""A3.1b: object- and function-level enforcement in `sqlite_guard.make_authorizer`.

Covers the full behavior contract: SQLITE_READ gated by
`tools.db.sql_surface.is_queryable`, SQLITE_FUNCTION gated by the frozen
19-entry allowlist (17 SQLite builtins + INSTR + GOVERNED_JLL_FLOOR, the
latter two added after auditing the real guarded-runtime SQL -- see
`tools/analyst_runtime/sqlite_guard.py`'s module docstring),
SQLITE_SELECT/SQLITE_RECURSIVE allowed unconditionally, everything else
denied.

Almost every fixture here is a scratch/temp database -- never
`memory/agente_toesca_v2.db`. The sole exception is
`test_rent_roll_governed_dataset_end_to_end_against_real_db`, which
deliberately runs the real `GovernedDatasetExecutor` + real
`catalog_v1.yaml` `source_sql` against the real production DB, strictly
read-only (mirrors the precedent already set by
`tests/analyst_runtime/test_governed_analytics_wiring.py`'s
`DB = Path("memory/agente_toesca_v2.db")`) -- it never writes, and is the
only way to prove the *actual* rent_roll dataset (not a hand-reproduced
approximation) executes end-to-end under the strict authorizer.

The schema84 view-dependency-chain regression check (case 18) replays
`tools/db/baseline.sql` -- the actual schema84 DDL, the same file
`tools.db.sql_surface`'s registry is generated against -- into an in-memory
database, so the views under test are the real ones, not hand-rewritten
approximations, while still never touching the business DB file.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.analyst_runtime.actions import RunSqlAction
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.sqlite_guard import ALLOWED_FUNCTIONS, make_authorizer
from tools.analyst_runtime.transport import ToolRequest
from tools.datasets.executor import DatasetFilter, DatasetMeasure, GovernedDatasetExecutor, GovernedDatasetQuery
from tools.db import sql_surface

REAL_DB = Path(__file__).resolve().parents[2] / "memory" / "agente_toesca_v2.db"

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_SQL = REPO_ROOT / "tools" / "db" / "baseline.sql"


def _make_fixture_db(path: Path) -> None:
    """A small scratch DB with one MODEL_QUERYABLE table, one INTERNAL table,
    and an UNCLASSIFIED table not present in the registry at all."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT PRIMARY KEY, nombre TEXT)")
    conn.execute("INSERT INTO dim_fondo VALUES ('PT', 'Parque Titanium')")
    conn.execute("INSERT INTO dim_fondo VALUES ('TRI', 'Rentas TRI')")
    # INTERNAL per sql_surface: present but must stay denied.
    conn.execute("CREATE TABLE dim_kpi (kpi_key TEXT PRIMARY KEY, valor REAL)")
    conn.execute("INSERT INTO dim_kpi VALUES ('x', 1.0)")
    # Not in the registry at all (a hypothetical migration-085+ object).
    conn.execute("CREATE TABLE staging_scratch_object (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO staging_scratch_object VALUES (1)")
    conn.commit()
    conn.close()


@pytest.fixture
def fixture_db(tmp_path) -> Path:
    path = tmp_path / "fixture.db"
    _make_fixture_db(path)
    return path


def _guarded_conn(db_path: Path, violations: list[str] | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.set_authorizer(make_authorizer(violations))
    return conn


# ---------------------------------------------------------------------------
# 1-7: SQLITE_READ enforcement via sql_surface.is_queryable
# ---------------------------------------------------------------------------

def test_model_queryable_table_select_allowed(fixture_db):
    conn = _guarded_conn(fixture_db)
    try:
        rows = conn.execute("SELECT fondo_key FROM dim_fondo ORDER BY fondo_key").fetchall()
        assert rows == [("PT",), ("TRI",)]
    finally:
        conn.close()


def test_model_queryable_view_select_allowed(tmp_path):
    """A view built purely on MODEL_QUERYABLE backing tables is queryable --
    reading it emits SQLITE_READ for the view name AND its backing tables,
    both of which must classify as MODEL_QUERYABLE."""
    path = tmp_path / "view_fixture.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT PRIMARY KEY, nombre TEXT)")
    conn.execute("INSERT INTO dim_fondo VALUES ('PT', 'Parque Titanium')")
    # fact_uf is a real MODEL_QUERYABLE view name; give it a matching
    # minimal backing definition for this scratch DB only.
    conn.execute("CREATE TABLE raw_uf_diaria (fecha TEXT PRIMARY KEY, valor REAL)")
    conn.execute("CREATE VIEW fact_uf AS SELECT fecha, valor FROM raw_uf_diaria")
    conn.commit()
    conn.close()

    assert "fact_uf" in sql_surface.MODEL_QUERYABLE
    assert "raw_uf_diaria" in sql_surface.MODEL_QUERYABLE

    conn = _guarded_conn(path)
    try:
        rows = conn.execute("SELECT * FROM fact_uf").fetchall()
        assert rows == []
    finally:
        conn.close()


def test_dim_kpi_denied(fixture_db):
    assert sql_surface.classify("dim_kpi") == "INTERNAL"
    conn = _guarded_conn(fixture_db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM dim_kpi")
    finally:
        conn.close()


def test_schema_version_denied(tmp_path):
    path = tmp_path / "schema_version.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version VALUES (84)")
    conn.commit()
    conn.close()

    assert sql_surface.classify("schema_version") == "INTERNAL"
    conn = _guarded_conn(path)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM schema_version")
    finally:
        conn.close()


def test_sqlite_master_denied(fixture_db):
    conn = _guarded_conn(fixture_db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT name FROM sqlite_master")
    finally:
        conn.close()


def test_sqlite_sequence_denied(tmp_path):
    path = tmp_path / "seq.db"
    conn = sqlite3.connect(path)
    # AUTOINCREMENT forces sqlite to create sqlite_sequence.
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('x')")
    conn.commit()
    conn.close()

    assert sql_surface.classify("sqlite_sequence") == "SQLITE_INTERNAL"
    conn = _guarded_conn(path)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM sqlite_sequence")
    finally:
        conn.close()


def test_unclassified_object_denied(fixture_db):
    assert sql_surface.classify("staging_scratch_object") == "UNCLASSIFIED"
    conn = _guarded_conn(fixture_db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM staging_scratch_object")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8-11: SQLITE_FUNCTION enforcement
# ---------------------------------------------------------------------------

def test_sum_allowed(fixture_db):
    assert "SUM" in ALLOWED_FUNCTIONS
    conn = _guarded_conn(fixture_db)
    try:
        (n,) = conn.execute("SELECT SUM(1) FROM dim_fondo").fetchone()
        assert n == 2
    finally:
        conn.close()


def test_json_extract_allowed(fixture_db):
    assert "JSON_EXTRACT" in ALLOWED_FUNCTIONS
    conn = _guarded_conn(fixture_db)
    try:
        (v,) = conn.execute(
            "SELECT JSON_EXTRACT('{\"a\":1}', '$.a') FROM dim_fondo LIMIT 1"
        ).fetchone()
        assert v == 1
    finally:
        conn.close()


def test_trim_allowed(fixture_db):
    assert "TRIM" in ALLOWED_FUNCTIONS
    conn = _guarded_conn(fixture_db)
    try:
        (v,) = conn.execute("SELECT TRIM('  x  ') FROM dim_fondo LIMIT 1").fetchone()
        assert v == "x"
    finally:
        conn.close()


def test_random_denied(fixture_db):
    assert "RANDOM" not in ALLOWED_FUNCTIONS
    conn = _guarded_conn(fixture_db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT RANDOM() FROM dim_fondo")
    finally:
        conn.close()


def test_instr_allowed(fixture_db):
    """`INSTR` is required by the real `rent_roll` governed dataset's
    `source_sql` in tools/datasets/catalog_v1.yaml (Apo3001 office floor
    parsing) -- added to the allowlist after auditing the guarded surface."""
    assert "INSTR" in ALLOWED_FUNCTIONS
    conn = _guarded_conn(fixture_db)
    try:
        (v,) = conn.execute("SELECT INSTR('abc def', ' ') FROM dim_fondo LIMIT 1").fetchone()
        assert v == 4
    finally:
        conn.close()


def test_custom_registered_function_governed_jll_floor_allowed(fixture_db):
    """`governed_jll_floor` is a custom Python function registered per
    connection via `conn.create_function` in tools/datasets/executor.py, not
    a SQLite builtin -- but SQLite still routes a call to it through
    SQLITE_FUNCTION with arg2 == the registered name, so the authorizer's
    name-string check treats it exactly like any other allowlisted name.
    The authorizer does not create the function itself -- it must actually
    be registered on the connection for the call to succeed at all."""
    assert "GOVERNED_JLL_FLOOR" in ALLOWED_FUNCTIONS
    conn = _guarded_conn(fixture_db)
    try:
        conn.create_function("governed_jll_floor", 1, lambda unidad: f"floor-{unidad}")
        (v,) = conn.execute(
            "SELECT governed_jll_floor(fondo_key) FROM dim_fondo WHERE fondo_key='PT'"
        ).fetchone()
        assert v == "floor-PT"
    finally:
        conn.close()


def test_custom_registered_function_not_in_allowlist_still_denied(fixture_db):
    """Registering a custom function on the connection does not, by itself,
    make SQLite skip the authorizer -- an arbitrary custom-registered name
    that is NOT in ALLOWED_FUNCTIONS must still be denied, proving the check
    is a genuine name-string allowlist and not merely "is this a builtin"."""
    conn = _guarded_conn(fixture_db)
    try:
        conn.create_function("totally_unvetted_custom_fn", 1, lambda x: x)
        assert "TOTALLY_UNVETTED_CUSTOM_FN" not in ALLOWED_FUNCTIONS
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(
                "SELECT totally_unvetted_custom_fn(fondo_key) FROM dim_fondo WHERE fondo_key='PT'"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 12: regression -- writes still denied
# ---------------------------------------------------------------------------

def test_write_statement_denied(fixture_db):
    conn = _guarded_conn(fixture_db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO dim_fondo VALUES ('X', 'Y')")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 13-14: CTEs (ordinary and recursive)
# ---------------------------------------------------------------------------

def test_ordinary_cte_allowed_when_reads_valid(fixture_db):
    conn = _guarded_conn(fixture_db)
    try:
        rows = conn.execute(
            "WITH x AS (SELECT fondo_key FROM dim_fondo) SELECT * FROM x ORDER BY fondo_key"
        ).fetchall()
        assert rows == [("PT",), ("TRI",)]
    finally:
        conn.close()


def test_recursive_cte_allowed_when_reads_valid(fixture_db):
    conn = _guarded_conn(fixture_db)
    try:
        rows = conn.execute(
            """
            WITH RECURSIVE counter(n) AS (
                SELECT 1
                UNION ALL
                SELECT n + 1 FROM counter WHERE n < (SELECT COUNT(*) FROM dim_fondo)
            )
            SELECT n FROM counter ORDER BY n
            """
        ).fetchall()
        assert rows == [(1,), (2,)]
    finally:
        conn.close()


def test_recursive_cte_still_denies_unclassified_backing_read(fixture_db):
    """A recursive CTE does not bypass object-level enforcement: if its
    non-recursive term reads an UNCLASSIFIED object, it is still denied."""
    conn = _guarded_conn(fixture_db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(
                """
                WITH RECURSIVE counter(n) AS (
                    SELECT id FROM staging_scratch_object
                    UNION ALL
                    SELECT n + 1 FROM counter WHERE n < 2
                )
                SELECT n FROM counter
                """
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 15: deterministic violation capture
# ---------------------------------------------------------------------------

def test_denied_query_produces_identical_violation_log_both_times(fixture_db):
    log_a: list[str] = []
    conn_a = sqlite3.connect(fixture_db)
    conn_a.set_authorizer(make_authorizer(log_a))
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn_a.execute("SELECT * FROM dim_kpi")
    finally:
        conn_a.close()

    log_b: list[str] = []
    conn_b = sqlite3.connect(fixture_db)
    conn_b.set_authorizer(make_authorizer(log_b))
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn_b.execute("SELECT * FROM dim_kpi")
    finally:
        conn_b.close()

    assert log_a == log_b
    assert log_a  # non-empty: something was actually captured


# ---------------------------------------------------------------------------
# 16-17: RunSqlAction end-to-end via LiveReadOnlySandbox and SnapshotSandbox
# ---------------------------------------------------------------------------

def test_run_sql_action_end_to_end_via_live_sandbox(fixture_db):
    sandbox = LiveReadOnlySandbox(fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(
        ToolRequest(
            call_id="1",
            name="run_sql",
            arguments={"query": "SELECT fondo_key FROM dim_fondo ORDER BY fondo_key"},
        )
    )
    assert result.ok is True
    assert '"PT"' in result.content


def test_run_sql_action_end_to_end_via_snapshot_sandbox(fixture_db):
    from eval.benchmark.snapshot import QueryLog, SnapshotSandbox

    sandbox = SnapshotSandbox.__new__(SnapshotSandbox)
    sandbox.path = fixture_db
    sandbox.log = QueryLog()
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(
        ToolRequest(
            call_id="1",
            name="run_sql",
            arguments={"query": "SELECT fondo_key FROM dim_fondo ORDER BY fondo_key"},
        )
    )
    assert result.ok is True
    assert '"PT"' in result.content


def test_run_sql_action_end_to_end_denies_unclassified_object(fixture_db):
    """RunSqlAction surfaces the authorizer's deny as a tool error, not a
    crash -- confirms the new object-level check is wired through the same
    seam used in production."""
    sandbox = LiveReadOnlySandbox(fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(
        ToolRequest(
            call_id="1",
            name="run_sql",
            arguments={"query": "SELECT * FROM staging_scratch_object"},
        )
    )
    assert result.ok is False
    assert "error" in result.content


# ---------------------------------------------------------------------------
# 18: schema84 view dependency chains stay queryable (regression check)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def schema84_conn():
    """The real schema84 DDL (tools/db/baseline.sql) replayed into an
    in-memory database -- never the business DB file. Proves the strict
    authorizer doesn't deny legitimate view dependency chains for the
    actual registry, not a hand-approximated one."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(BASELINE_SQL.read_text(encoding="utf-8"))
    conn.set_authorizer(make_authorizer())
    yield conn
    conn.close()


@pytest.mark.parametrize(
    "view_name",
    [
        "v_serie_patrimonio",
        "fact_uf",
        "fact_precio_cuota",
        "v_activo_fondo_efectivo",
        "v_vacancia_activo",
        "raw_valor_cuota_line",
        "v_capital_suscrito_serie",
        "v_flujos_tir_serie",
    ],
)
def test_representative_schema84_views_remain_queryable(schema84_conn, view_name):
    assert view_name in sql_surface.MODEL_QUERYABLE
    # Executes with zero rows in every backing table -- this asserts the
    # authorizer admits the whole dependency chain, not that there's data.
    schema84_conn.execute(f"SELECT * FROM {view_name}").fetchall()


def test_all_schema84_model_queryable_views_remain_queryable(schema84_conn):
    """Exhaustive variant of the above over every registered view, not just
    the representative handful -- belt-and-suspenders regression coverage."""
    failures = []
    for view_name in sorted(sql_surface.MODEL_QUERYABLE_VIEWS):
        try:
            schema84_conn.execute(f"SELECT * FROM {view_name}").fetchall()
        except sqlite3.DatabaseError as exc:
            failures.append(f"{view_name}: {exc}")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Real rent_roll governed dataset path (real code, real catalog SQL, real DB
# -- strictly read-only). Proves INSTR + GOVERNED_JLL_FLOOR were the actual,
# complete delta required: this is the exact executor + catalog SQL that
# `tests/analyst_runtime/test_governed_analytics_wiring.py` and
# `tests/analyst_runtime/test_schema_search.py` exercise, which failed with
# `not authorized to use function: instr` before this amendment.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not REAL_DB.exists(), reason="memory/agente_toesca_v2.db not present")
def test_rent_roll_governed_dataset_end_to_end_against_real_db():
    before = REAL_DB.stat()
    executor = GovernedDatasetExecutor(REAL_DB)
    query = GovernedDatasetQuery(
        dataset="rent_roll",
        filters=(
            DatasetFilter("activo_key", "eq", "Apo3001"),
            DatasetFilter("periodo", "eq", "2026-06"),
        ),
        group_by=("arrendatario",),
        measures=(DatasetMeasure("gla_m2", "sum"),),
        order_by="gla_m2",
        descending=True,
        limit=5,
    )
    result = executor.execute(query)
    assert isinstance(result.rows, tuple)
    after = REAL_DB.stat()
    assert before.st_mtime == after.st_mtime
    assert before.st_size == after.st_size
