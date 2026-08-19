"""Read-only sandbox over the live production database.

Stage A2 of the Alpha v0.1 build. Unlike `SnapshotSandbox` (a pinned,
immutable benchmark fixture), `LiveReadOnlySandbox` targets a database that
can legitimately change between connections (the real
`memory/agente_toesca_v2.db`, updated by ingestion runs) -- so it opens with
`mode=ro` only, deliberately NOT `immutable=1`. `immutable=1` tells sqlite it
may cache assumptions about the file never changing, which would be
incorrect here.

No migrations, no journal/write side effects. This class must never write to
the database file it targets.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.analyst_runtime.sqlite_guard import make_authorizer

_authorizer = make_authorizer()


class LiveReadOnlySandbox:
    """Hands out guarded, read-only connections to a live sqlite database."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def connect(self, guard: bool = True) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"SQLite database does not exist: {self.db_path}")
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        if guard:
            conn.set_authorizer(_authorizer)
        return conn
