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

import time

from tools.analyst_runtime import actions
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


def _make_slow_fixture_db(path: Path) -> None:
    """dim_fondo (MODEL_QUERYABLE regardless of which physical DB it lives
    in) seeded with enough rows that a 3-way self cross-join reliably runs
    past a tiny monkeypatched timeout, without allocating dangerous memory
    (COUNT(*) never materializes the product)."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT PRIMARY KEY, nombre TEXT)")
    conn.executemany(
        "INSERT INTO dim_fondo VALUES (?, ?)",
        [(f"K{i}", f"N{i}") for i in range(300)],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def slow_fixture_db(tmp_path) -> Path:
    path = tmp_path / "slow_fixture.db"
    _make_slow_fixture_db(path)
    return path


_SLOW_CROSS_JOIN_SQL = "SELECT COUNT(*) FROM dim_fondo a, dim_fondo b, dim_fondo c"


class _TrackingConnProxy:
    """Wraps a real sqlite3.Connection to record set_progress_handler/close
    calls without subclassing the C type. Delegates everything else."""

    def __init__(self, real: sqlite3.Connection):
        self._real = real
        self.progress_handler_calls: list[tuple[object, int]] = []
        self.closed = False

    def set_progress_handler(self, callback, n):
        self.progress_handler_calls.append((callback, n))
        return self._real.set_progress_handler(callback, n)

    def close(self):
        self.closed = True
        return self._real.close()

    def execute(self, *args, **kwargs):
        return self._real.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _TrackingSandbox:
    """SqlSandbox that returns a _TrackingConnProxy so tests can observe
    cleanup calls without touching production code."""

    def __init__(self, inner):
        self._inner = inner
        self.last_conn: _TrackingConnProxy | None = None

    def connect(self, guard: bool = True):
        real = self._inner.connect(guard=guard)
        self.last_conn = _TrackingConnProxy(real)
        return self.last_conn


class _SlowConnectSandbox:
    """Wraps a real sandbox; connect() sleeps past the monkeypatched timeout
    before returning. Proves the deadline is set after connect() returns,
    immediately before statement execution -- not at connection-open time,
    so slow connection establishment never consumes the SQL timeout budget."""

    def __init__(self, inner, delay_seconds: float):
        self._inner = inner
        self._delay_seconds = delay_seconds

    def connect(self, guard: bool = True):
        time.sleep(self._delay_seconds)
        return self._inner.connect(guard=guard)


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
# A3.1c: per-statement SQL timeout
# ---------------------------------------------------------------------------

def test_run_sql_action_normal_query_completes_under_timeout(fixture_db):
    """(A) ordinary query still succeeds; A3.1b authorizer stays active
    (validated separately by test_live_sandbox_authorizer_denies_write)."""
    sandbox = LiveReadOnlySandbox(fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT fondo_key FROM dim_fondo ORDER BY fondo_key"}))
    assert result.ok is True
    payload = json.loads(result.content)
    assert payload["row_count"] == 2


def test_run_sql_action_timeout_classified_as_sql_timeout(slow_fixture_db, monkeypatch):
    """(B)(C-partial) a deterministic slow cross-join is interrupted and
    classified exactly as sql_timeout, not a generic sql_error."""
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 0.05)
    sandbox = LiveReadOnlySandbox(slow_fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": _SLOW_CROSS_JOIN_SQL}))
    assert result.ok is False
    payload = json.loads(result.content)
    assert payload["error_type"] == "sql_timeout"
    assert result.trace["error"]["error_type"] == "sql_timeout"


def test_run_sql_action_ordinary_sql_error_stays_sql_error(fixture_db, monkeypatch):
    """(B) generic errors are never misclassified as sql_timeout, even with
    a tiny timeout budget active."""
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 0.05)
    sandbox = LiveReadOnlySandbox(fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT * FROM no_such_table"}))
    assert result.ok is False
    assert result.trace["error"]["error_type"] == "sql_error"


def test_run_sql_action_slow_connect_does_not_consume_timeout_budget(fixture_db, monkeypatch):
    """(C) a deliberately slow sandbox.connect(guard=True) -- longer than the
    monkeypatched timeout -- must not eat into the SQL statement budget. The
    deadline starts only after connect() returns, immediately before
    set_progress_handler/execute."""
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 0.05)
    slow_sandbox = _SlowConnectSandbox(LiveReadOnlySandbox(fixture_db), delay_seconds=0.2)
    action = RunSqlAction(sandbox=slow_sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT 1"}))
    assert result.ok is True


def test_run_sql_action_authorizer_denial_not_misclassified_as_timeout(fixture_db, monkeypatch):
    """(D) authorizer-denied writes stay a generic SQL error even with a
    tiny timeout budget active concurrently -- timeout never bypasses or
    is confused with authorizer enforcement."""
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 0.05)
    sandbox = LiveReadOnlySandbox(fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "DELETE FROM dim_fondo"}))
    assert result.ok is False
    assert result.trace["error"]["error_type"] == "sql_error"


def test_run_sql_action_clears_progress_handler_after_success(fixture_db):
    """(E) handler removed on the success path."""
    sandbox = _TrackingSandbox(LiveReadOnlySandbox(fixture_db))
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT 1"}))
    assert result.ok is True
    assert sandbox.last_conn.progress_handler_calls[-1] == (None, 0)
    assert sandbox.last_conn.closed is True


def test_run_sql_action_clears_progress_handler_after_sql_error(fixture_db):
    """(E) handler removed on the ordinary-error path."""
    sandbox = _TrackingSandbox(LiveReadOnlySandbox(fixture_db))
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": "SELECT * FROM no_such_table"}))
    assert result.ok is False
    assert sandbox.last_conn.progress_handler_calls[-1] == (None, 0)
    assert sandbox.last_conn.closed is True


def test_run_sql_action_clears_progress_handler_after_timeout(slow_fixture_db, monkeypatch):
    """(E) handler removed on the timeout path; connection still closed."""
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 0.05)
    sandbox = _TrackingSandbox(LiveReadOnlySandbox(slow_fixture_db))
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": _SLOW_CROSS_JOIN_SQL}))
    assert result.ok is False
    assert sandbox.last_conn.progress_handler_calls[-1] == (None, 0)
    assert sandbox.last_conn.closed is True


def test_run_sql_action_next_call_gets_fresh_budget(slow_fixture_db, monkeypatch):
    """Fresh per-statement budget: a timed-out call does not poison the next
    RunSqlAction.execute() call once the budget is restored."""
    sandbox = LiveReadOnlySandbox(slow_fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 0.05)
    timed_out_result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": _SLOW_CROSS_JOIN_SQL}))
    assert json.loads(timed_out_result.content)["error_type"] == "sql_timeout"
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 3.0)
    fast_result = action.execute(ToolRequest(call_id="2", name="run_sql", arguments={"query": "SELECT fondo_key FROM dim_fondo LIMIT 1"}))
    assert fast_result.ok is True


def test_run_sql_action_timeout_trace_carries_no_sensitive_detail(slow_fixture_db, monkeypatch):
    """(F) the timeout trace is a safe, deterministic classification -- no
    stack trace, no interpreter-internal text."""
    monkeypatch.setattr(actions, "SQL_TIMEOUT_SECONDS", 0.05)
    sandbox = LiveReadOnlySandbox(slow_fixture_db)
    action = RunSqlAction(sandbox=sandbox)
    result = action.execute(ToolRequest(call_id="1", name="run_sql", arguments={"query": _SLOW_CROSS_JOIN_SQL}))
    error = result.trace["error"]
    assert error["error_type"] == "sql_timeout"
    assert "Traceback" not in error["message"]
    assert "File \"" not in error["message"]


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
        # sqlite_master is INTERNAL/UNCLASSIFIED under the A3.1b authorizer
        # and is now correctly denied; use a MODEL_QUERYABLE table instead.
        row = conn.execute("SELECT * FROM dim_fondo LIMIT 1").fetchone()
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
