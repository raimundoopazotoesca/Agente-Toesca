"""Pinned, read-only DB snapshot for the benchmark.

The productive DB is already versioned in git, so the snapshot is a *pin*
(commit + blob + sha256) rather than a 32 MB copy checked into the repo.
`materialize()` extracts the pinned blob into a gitignored cache and
verifies its hash before anyone reads it.

Every connection handed out is:
  - read-only and immutable at the sqlite level;
  - guarded by an authorizer that denies DDL/DML/PRAGMA/ATTACH (gate F4);
  - traced, so the *sandbox* records the SQL actually executed.

That last point matters for architecture neutrality: `queries` is captured
here, not self-reported by the system under test, so no adapter can be
rewarded for reporting well or lie about what it ran.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCHMARK_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_DIR.parents[1]
LOCK_PATH = BENCHMARK_DIR / "snapshot.lock"
CACHE_DIR = BENCHMARK_DIR / ".cache"


class SnapshotError(Exception):
    """Snapshot could not be materialized or failed verification."""


class UnsafeDatabaseAccess(Exception):
    """The system under test attempted a write, PRAGMA or ATTACH (gate F4)."""


def load_lock(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or LOCK_PATH).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize(lock: dict[str, Any] | None = None, force: bool = False) -> Path:
    """Extract the pinned blob into the cache and verify it. Returns the path."""
    lock = lock or load_lock()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"snapshot-{lock['benchmark_version']}-{lock['sha256'][:12]}.db"

    if target.exists() and not force:
        if _sha256(target) == lock["sha256"]:
            return target
        target.unlink()

    try:
        blob = subprocess.run(
            ["git", "cat-file", "blob", lock["blob_sha"]],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SnapshotError(
            f"could not read pinned blob {lock['blob_sha']} from git "
            f"(commit {lock['git_commit']}): {exc}"
        ) from exc

    target.write_bytes(blob)
    actual = _sha256(target)
    if actual != lock["sha256"]:
        target.unlink()
        raise SnapshotError(
            f"snapshot hash mismatch: expected {lock['sha256']}, got {actual}. "
            "The pin is wrong or the blob changed -- do not proceed."
        )
    return target


def verify_row_counts(conn: sqlite3.Connection, lock: dict[str, Any] | None = None) -> None:
    """Cheap tripwire: the pinned world must have the pinned shape."""
    lock = lock or load_lock()
    problems = []
    for table, expected in lock.get("row_counts", {}).items():
        actual = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if actual != expected:
            problems.append(f"{table}: expected {expected}, got {actual}")
    if problems:
        raise SnapshotError("snapshot row counts drifted: " + "; ".join(problems))


# sqlite authorizer actions that are safe for a benchmark reader.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


@dataclass
class QueryLog:
    """SQL captured by the sandbox, not reported by the system under test."""

    statements: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.statements.clear()
        self.violations.clear()

    @property
    def distinct(self) -> set[str]:
        return {" ".join(s.split()).rstrip(";").lower() for s in self.statements}

    def touched_tables(self, known_tables: set[str]) -> set[str]:
        """Tables named in the captured SQL. Substring match is enough here:
        the candidate set is the snapshot's own table/view names."""
        blob = " ".join(self.distinct)
        return {t for t in known_tables if t.lower() in blob}


class SnapshotSandbox:
    """Hands out guarded, traced connections to the pinned snapshot."""

    def __init__(self, path: Path | None = None, lock: dict[str, Any] | None = None):
        self.lock = lock or load_lock()
        self.path = path or materialize(self.lock)
        self.log = QueryLog()

    @property
    def benchmark_today(self) -> str:
        return self.lock["benchmark_today"]

    def _authorizer(self, action: int, arg1, arg2, db_name, trigger) -> int:
        if action in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_OK
        detail = f"action={action} arg1={arg1!r} arg2={arg2!r}"
        self.log.violations.append(detail)
        return sqlite3.SQLITE_DENY

    def connect(self, guard: bool = True) -> sqlite3.Connection:
        """Open the snapshot read-only.

        `guard=False` is for the benchmark's own ground-truth resolution,
        which is trusted code; the system under test always gets guard=True.
        """
        uri = f"file:{self.path.as_posix()}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        conn.set_trace_callback(self.log.statements.append)
        if guard:
            conn.set_authorizer(self._authorizer)
        return conn

    def known_tables(self) -> set[str]:
        conn = self.connect(guard=False)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows}

    def verify(self) -> None:
        conn = self.connect(guard=False)
        try:
            verify_row_counts(conn, self.lock)
        finally:
            conn.close()
