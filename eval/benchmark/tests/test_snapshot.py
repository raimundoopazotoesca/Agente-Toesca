from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.snapshot import SnapshotError, SnapshotSandbox, load_lock
from eval.benchmark.version import BENCHMARK_TODAY, BENCHMARK_VERSION


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


def test_lock_matches_version_module():
    lock = load_lock()
    assert lock["benchmark_version"] == BENCHMARK_VERSION
    assert lock["benchmark_today"] == BENCHMARK_TODAY


def test_materialize_verifies_hash(sandbox):
    assert sandbox.path.exists()
    assert sandbox.path.stat().st_size > 0


def test_row_counts_match_pin(sandbox):
    sandbox.verify()  # raises SnapshotError on drift


def test_bad_hash_is_rejected(tmp_path):
    from eval.benchmark import snapshot as snap

    lock = dict(load_lock())
    lock["sha256"] = "0" * 64
    original_cache = snap.CACHE_DIR
    snap.CACHE_DIR = tmp_path
    try:
        with pytest.raises(SnapshotError, match="hash mismatch"):
            snap.materialize(lock, force=True)
    finally:
        snap.CACHE_DIR = original_cache


def test_reads_are_allowed(sandbox):
    conn = sandbox.connect()
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM dim_activo").fetchone()
        assert n == 17
    finally:
        conn.close()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM dim_activo",
        "UPDATE dim_activo SET nombre = 'x'",
        "INSERT INTO dim_activo (activo_key) VALUES ('x')",
        "CREATE TABLE t (a int)",
        "DROP TABLE dim_activo",
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA writable_schema = 1",
    ],
)
def test_unsafe_statements_are_denied(sandbox, sql):
    """Gate F4: the sandbox refuses, the system under test cannot opt out."""
    conn = sandbox.connect()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)
    finally:
        conn.close()


def test_queries_are_captured_by_the_sandbox(sandbox):
    """Architecture neutrality: the log is written here, not self-reported."""
    sandbox.log.reset()
    conn = sandbox.connect()
    try:
        conn.execute("SELECT activo_key FROM dim_activo WHERE fondo_key = 'PT'").fetchall()
        conn.execute("SELECT COUNT(*) FROM raw_er_activo_line").fetchall()
    finally:
        conn.close()
    assert len(sandbox.log.distinct) == 2
    assert sandbox.log.touched_tables(sandbox.known_tables()) >= {
        "dim_activo",
        "raw_er_activo_line",
    }


def test_snapshot_is_immutable_across_connections(sandbox):
    """Two connections see the same world; nothing the SUT does can persist."""
    a = sandbox.connect(guard=False)
    b = sandbox.connect(guard=False)
    try:
        assert (
            a.execute("SELECT COUNT(*) FROM derived_kpi").fetchone()
            == b.execute("SELECT COUNT(*) FROM derived_kpi").fetchone()
        )
    finally:
        a.close()
        b.close()
