"""Monkeypatch-based sqlite3 guard used to point an existing module (like
`tools.db_chat`) at the pinned snapshot without touching its source.

`tools/db_chat.py` opens its own sqlite3 connections in a couple of places
(some already read-only via a `mode=ro` URI, at least one plain
`sqlite3.connect(DEFAULT_DB_PATH)`). Rather than editing runtime code to
accept an injectable connection -- which the design explicitly rules out
("no modifiques runtime del asistente salvo... adapter completamente
neutral") -- this wraps `sqlite3.connect` for the duration of one adapter
call so that:

  - every connection opened against the snapshot path is forced read-only
    and immutable, regardless of how the caller asked for it;
  - every such connection gets the sandbox's authorizer (gate F4) and its
    trace callback (query capture), so `queries` reflects exactly what the
    system under test ran -- not what it claims to have run.

This lives under eval/benchmark/adapters/, is only ever active inside a
`with guarded_sqlite(sandbox):` block, and is restored unconditionally in
`finally`. It never patches anything outside this process.
"""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

from eval.benchmark.snapshot import SnapshotSandbox


def _to_ro_uri(path: str, snapshot_path: Path) -> str | None:
    """If `path` (or the URI it's wrapped in) targets the snapshot file,
    return a forced read-only URI. Otherwise return None -- untouched."""
    raw = path
    if raw.startswith("file:"):
        raw = raw[len("file:") :].split("?", 1)[0]
    try:
        resolved = Path(raw).resolve()
    except OSError:
        return None
    if resolved != snapshot_path.resolve():
        return None
    return f"file:{snapshot_path.as_posix()}?mode=ro&immutable=1"


@contextlib.contextmanager
def guarded_sqlite(sandbox: SnapshotSandbox):
    """Force every sqlite3.connect() call in this process onto the guarded,
    traced snapshot for the duration of the block."""
    original_connect = sqlite3.connect
    snapshot_path = sandbox.path

    def guarded_connect(database, *args, **kwargs):
        forced_uri = _to_ro_uri(str(database), snapshot_path)
        if forced_uri is None:
            # Not the snapshot: leave it alone (e.g. sqlite3.connect(":memory:")
            # used internally by some library). Nothing in this benchmark
            # should ever hit a non-snapshot on-disk DB, but we don't want a
            # library implementation detail to break on that assumption.
            return original_connect(database, *args, **kwargs)

        kwargs = dict(kwargs)
        kwargs["uri"] = True
        conn = original_connect(forced_uri, **{k: v for k, v in kwargs.items() if k != "check_same_thread"})
        conn.set_trace_callback(sandbox.log.statements.append)
        conn.set_authorizer(sandbox._authorizer)  # noqa: SLF001 -- same package family
        return conn

    sqlite3.connect = guarded_connect
    try:
        yield
    finally:
        sqlite3.connect = original_connect
