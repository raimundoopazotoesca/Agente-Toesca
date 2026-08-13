from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters._sqlite_guard import guarded_sqlite
from eval.benchmark.adapters.base import Artifact, Session, Turn, Usage
from eval.benchmark.snapshot import SnapshotSandbox


@pytest.fixture(scope="module")
def sandbox() -> SnapshotSandbox:
    return SnapshotSandbox()


class _StubSession:
    """Minimal adapter used to test the contract shape itself, without a
    real LLM in the loop. Track A/B are tested for their own translation
    logic separately; this proves the Protocol is actually satisfiable."""

    def __init__(self, sandbox: SnapshotSandbox):
        self.sandbox = sandbox

    def ask(self, message: str) -> Turn:
        conn = self.sandbox.connect()
        try:
            (n,) = conn.execute("SELECT COUNT(*) FROM dim_activo").fetchone()
        finally:
            conn.close()
        return Turn(
            text=f"hay {n} activos",
            artifacts=[Artifact(kind="table", payload=[["activos", n]])],
            usage=Usage(provider="stub", calls=1),
            queries=list(self.sandbox.log.statements),
        )


def test_stub_session_satisfies_protocol(sandbox):
    session: Session = _StubSession(sandbox)
    turn = session.ask("cuantos activos hay?")
    assert "17" in turn.text
    assert turn.artifacts[0].kind == "table"
    assert turn.queries  # captured by the sandbox, present on the Turn


def test_guarded_sqlite_forces_readonly_on_snapshot_path(sandbox):
    with guarded_sqlite(sandbox):
        conn = sqlite3.connect(str(sandbox.path))
        try:
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM dim_activo")
        finally:
            conn.close()


def test_guarded_sqlite_captures_queries_from_plain_connect(sandbox):
    sandbox.log.reset()
    with guarded_sqlite(sandbox):
        conn = sqlite3.connect(str(sandbox.path))
        try:
            conn.execute("SELECT COUNT(*) FROM dim_fondo").fetchall()
        finally:
            conn.close()
    assert any("dim_fondo" in s for s in sandbox.log.statements)


def test_guarded_sqlite_restores_connect_after_block(sandbox):
    original = sqlite3.connect
    with guarded_sqlite(sandbox):
        assert sqlite3.connect is not original
    assert sqlite3.connect is original


def test_guarded_sqlite_leaves_unrelated_paths_alone(sandbox, tmp_path):
    other_db = tmp_path / "scratch.db"
    with guarded_sqlite(sandbox):
        conn = sqlite3.connect(str(other_db))
        try:
            conn.execute("CREATE TABLE t (a int)")  # would raise if guarded
            conn.execute("INSERT INTO t VALUES (1)")
        finally:
            conn.close()
    assert other_db.exists()
