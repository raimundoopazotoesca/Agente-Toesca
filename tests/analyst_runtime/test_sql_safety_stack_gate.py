"""A3.1e full-stack gate for structural validation, authorization and limits.

Every case drives the public ``RunSqlAction`` against the real Live and
Snapshot sandbox implementations over a disposable SQLite database.  This is
deliberately an integration gate: it does not reimplement any guard policy.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from eval.benchmark.snapshot import QueryLog, SnapshotSandbox
from tests.analyst_runtime.test_sandbox import _TrackingSandbox
from tools.analyst_runtime import actions
from tools.analyst_runtime.actions import MAX_ROWS_RETURNED, RunSqlAction, validate_sql
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ToolRequest


def _make_safety_db(path: Path) -> None:
    """Build a disposable DB with queryable, internal and unclassified data."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT PRIMARY KEY, nombre TEXT)")
    conn.executemany(
        "INSERT INTO dim_fondo VALUES (?, ?)",
        [(f"F{index:03d}", f"Fondo {index:03d}") for index in range(60)],
    )
    # Neither name belongs to MODEL_QUERYABLE; both must be stopped by the
    # authorizer rather than by the structural validator.
    conn.execute("CREATE TABLE internal_ledger (value INTEGER)")
    conn.execute("INSERT INTO internal_ledger VALUES (1)")
    conn.execute("CREATE TABLE staging_scratch_object (value INTEGER)")
    conn.execute("INSERT INTO staging_scratch_object VALUES (1)")
    conn.commit()
    conn.close()


@pytest.fixture
def safety_db(tmp_path) -> Path:
    path = tmp_path / "a3-1e-safety.db"
    _make_safety_db(path)
    return path


def _snapshot_sandbox(path: Path) -> SnapshotSandbox:
    """Use the real SnapshotSandbox connection path without materialization."""
    sandbox = SnapshotSandbox.__new__(SnapshotSandbox)
    sandbox.path = path
    sandbox.log = QueryLog()
    return sandbox


def _sandbox(kind: str, path: Path):
    if kind == "live":
        return LiveReadOnlySandbox(path)
    if kind == "snapshot":
        return _snapshot_sandbox(path)
    raise AssertionError(f"unknown sandbox kind: {kind}")


def _run(kind: str, path: Path, query: str):
    return RunSqlAction(_sandbox(kind, path)).execute(
        ToolRequest("a3-1e", "run_sql", {"query": query})
    )


def _error_type(result) -> str:
    assert result.ok is False
    assert result.evidence is None
    return result.trace["error"]["error_type"]


@pytest.mark.parametrize("kind", ["live", "snapshot"])
def test_queryable_objects_allowed_functions_and_governed_udf_execute(kind, safety_db):
    """A queryable object plus scalar/aggregate/date/string functions succeeds."""
    sandbox = _sandbox(kind, safety_db)
    original_connect = sandbox.connect

    # The production governed dataset path registers this UDF per connection.
    # This wrapper only supplies that registration; authorization and execution
    # still use the actual selected sandbox and RunSqlAction stack.
    def connect_with_governed_udf(guard=True):
        conn = original_connect(guard=guard)
        conn.create_function("governed_jll_floor", 1, lambda value: 12)
        return conn

    sandbox.connect = connect_with_governed_udf
    query = """
        SELECT
            SUM(ABS(1)), AVG(1), COUNT(*), MIN(fondo_key), MAX(fondo_key),
            ROUND(1.234, 2), UPPER('a'), LOWER('A'), SUBSTR('abc', 2),
            DATE('2020-01-02'), STRFTIME('%Y', '2020-01-02'),
            COALESCE(NULL, 'x'), JSON_EXTRACT('{\"x\": 1}', '$.x'),
            NULLIF(1, 2), 'abc' LIKE 'a%', TRIM(' x '), INSTR('abc', 'b'),
            GOVERNED_JLL_FLOOR('Piso 12')
        FROM dim_fondo
    """
    result = RunSqlAction(sandbox).execute(ToolRequest("a3-1e", "run_sql", {"query": query}))

    assert result.ok is True
    # A3.2b: run_sql now carries controlled_sql evidence -- facts stays
    # empty (SQL output is not a governed claim), the bounded rows live on
    # result.rows instead.
    assert result.evidence is not None
    assert result.evidence.evidence_class == "controlled_sql"
    assert result.evidence.facts == ()
    payload = json.loads(result.content)
    assert payload["rows"][0][-1] == 12
    assert payload["rows"][0][2] == 60


@pytest.mark.parametrize("kind", ["live", "snapshot"])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM internal_ledger",
        "SELECT name FROM sqlite_master",
        "SELECT * FROM staging_scratch_object",
        "SELECT * FROM no_such_table",
    ],
)
def test_structurally_valid_nonqueryable_access_is_denied_by_authorizer(kind, safety_db, query):
    """Object policy is enforced after structural validation, by SQLite."""
    assert validate_sql(query) is None
    assert _error_type(_run(kind, safety_db, query)) == "sql_error"


@pytest.mark.parametrize("kind", ["live", "snapshot"])
@pytest.mark.parametrize("query", ["SELECT RANDOM()", "SELECT load_extension('x')"])
def test_arbitrary_functions_are_denied_by_authorizer_not_structure(kind, safety_db, query):
    assert validate_sql(query) is None
    assert _error_type(_run(kind, safety_db, query)) == "sql_error"


@pytest.mark.parametrize(
    "query",
    [
        "",
        " \n\t ",
        "SELECT 1; SELECT 2",
        "SELECT 1;;",
        "SELECT ';'",
        "SELECT 1 /* ; */",
        "SELECT 1 -- ;\n",
        "SELECT 1 -- comment ;\n",
        'SELECT "quoted;identifier" FROM dim_fondo',
        "INSERT INTO dim_fondo VALUES ('X', 'Y')",
        "UPDATE dim_fondo SET nombre = 'x'",
        "DELETE FROM dim_fondo",
        "CREATE TABLE x (a INTEGER)",
        "DROP TABLE dim_fondo",
        "ALTER TABLE dim_fondo RENAME TO fondos",
        "PRAGMA table_info(dim_fondo)",
        "EXPLAIN SELECT 1",
    ],
)
def test_structural_gate_rejects_multistatement_literals_comments_and_nonselect_heads(safety_db, query):
    """These failures happen before any sandbox connection or authorizer call."""
    sandbox = _snapshot_sandbox(safety_db)
    result = RunSqlAction(sandbox).execute(ToolRequest("a3-1e", "run_sql", {"query": query}))

    assert result.ok is False
    assert result.evidence is None
    assert "error_type" not in json.loads(result.content)
    assert "error" in result.trace
    assert sandbox.log.statements == []
    assert sandbox.log.violations == []


@pytest.mark.parametrize("kind", ["live", "snapshot"])
@pytest.mark.parametrize("query", ["SELECT 1;", " \n SELECT 1 ; \t "])
def test_one_trailing_semicolon_with_surrounding_whitespace_is_accepted(kind, safety_db, query):
    result = _run(kind, safety_db, query)
    assert result.ok is True
    assert json.loads(result.content)["rows"] == [[1]]


@pytest.mark.parametrize("kind", ["live", "snapshot"])
def test_with_select_cte_is_accepted_end_to_end(kind, safety_db):
    """A WITH ... SELECT shape (read-only CTE) executes successfully."""
    query = "WITH counted AS (SELECT COUNT(*) AS n FROM dim_fondo) SELECT n FROM counted"
    result = _run(kind, safety_db, query)

    assert result.ok is True
    assert result.evidence is not None
    assert result.evidence.evidence_class == "controlled_sql"
    assert json.loads(result.content)["rows"] == [[60]]


@pytest.mark.parametrize("kind", ["live", "snapshot"])
@pytest.mark.parametrize(
    "query",
    [
        "WITH x AS (SELECT 1) INSERT INTO dim_fondo VALUES ('X', 'Y')",
        "WITH x AS (SELECT 1) UPDATE dim_fondo SET nombre = 'x'",
        "WITH x AS (SELECT 1) DELETE FROM dim_fondo",
    ],
)
def test_with_cte_reaches_sqlite_and_authorizer_denies_dml_shape(kind, safety_db, query):
    assert validate_sql(query) is None
    result = _run(kind, safety_db, query)

    assert _error_type(result) == "sql_error"
    # A fresh allowed call verifies that the denied CTE did not mutate data.
    check = _run(kind, safety_db, "SELECT COUNT(*) FROM dim_fondo")
    assert json.loads(check.content)["rows"] == [[60]]


_TIMEOUT_SQL = (
    "WITH RECURSIVE counter(value) AS "
    "(VALUES(1) UNION ALL SELECT value + 1 FROM counter WHERE value < 1000000000) "
    "SELECT SUM(value) FROM counter"
)


@pytest.mark.parametrize("kind", ["live", "snapshot"])
def test_recursive_query_times_out_and_remains_distinct_from_authorizer_denial(kind, safety_db):
    """The 3-second production budget, not a monkeypatched timing race, fires."""
    timeout_result = _run(kind, safety_db, _TIMEOUT_SQL)
    assert _error_type(timeout_result) == "sql_timeout"
    assert json.loads(timeout_result.content)["error_type"] == "sql_timeout"
    assert "Traceback" not in timeout_result.trace["error"]["message"]
    assert "File \"" not in timeout_result.trace["error"]["message"]

    denied_result = _run(kind, safety_db, "SELECT RANDOM()")
    assert _error_type(denied_result) == "sql_error"


@pytest.mark.parametrize("outcome_query, timeout", [
    ("SELECT 1", False),
    ("SELECT * FROM no_such_table", False),
    (_TIMEOUT_SQL, True),
])
def test_progress_handler_and_connection_cleanup_cover_success_error_and_timeout(safety_db, outcome_query, timeout):
    """Reuses the A3.1c tracking double; cleanup belongs to RunSqlAction."""
    sandbox = _TrackingSandbox(LiveReadOnlySandbox(safety_db))
    result = RunSqlAction(sandbox).execute(ToolRequest("a3-1e", "run_sql", {"query": outcome_query}))

    assert result.ok is (not timeout and outcome_query == "SELECT 1")
    if timeout:
        assert _error_type(result) == "sql_timeout"
    elif not result.ok:
        assert _error_type(result) == "sql_error"
    assert sandbox.last_conn.progress_handler_calls[0][1] == actions.SQL_PROGRESS_OPCODES
    assert sandbox.last_conn.progress_handler_calls[-1] == (None, 0)
    assert sandbox.last_conn.closed is True


@pytest.mark.parametrize("kind", ["live", "snapshot"])
def test_existing_row_limit_is_enforced_without_changing_its_contract(kind, safety_db):
    result = _run(kind, safety_db, "SELECT fondo_key FROM dim_fondo ORDER BY fondo_key")
    payload = json.loads(result.content)

    assert result.ok is True
    assert len(payload["rows"]) == MAX_ROWS_RETURNED
    assert payload["row_count"] == MAX_ROWS_RETURNED


@pytest.mark.parametrize(
    "query, expected_ok, expected_error_type",
    [
        ("SELECT COUNT(*) FROM dim_fondo", True, None),
        ("SELECT * FROM internal_ledger", False, "sql_error"),
        ("SELECT RANDOM()", False, "sql_error"),
        ("SELECT 1; SELECT 2", False, "sql_error"),
        ("DELETE FROM dim_fondo", False, "sql_error"),
        (_TIMEOUT_SQL, False, "sql_timeout"),
        ("SELECT fondo_key FROM dim_fondo ORDER BY fondo_key", True, None),
    ],
)
def test_live_and_snapshot_enforce_equivalent_full_stack_policy(safety_db, query, expected_ok, expected_error_type):
    """Parity gate: text may differ, but safety outcomes must not."""
    results = [_run(kind, safety_db, query) for kind in ("live", "snapshot")]

    assert [result.ok for result in results] == [expected_ok, expected_ok]
    actual_error_types = [
        result.trace.get("error", {}).get("error_type", "sql_error")
        for result in results
    ]
    assert actual_error_types == [expected_error_type or "sql_error"] * 2
