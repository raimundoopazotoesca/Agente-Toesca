"""Shared read-only sqlite3 authorizer, used by every SqlSandbox implementation.

Extracted (Stage A2 of the Alpha v0.1 build) from the `_authorizer` method
that lived on `eval.benchmark.snapshot.SnapshotSandbox`. There is exactly one
copy of this logic in the codebase: `SnapshotSandbox` now imports
`make_authorizer` from here instead of defining its own bound method, and
`LiveReadOnlySandbox` (live_sandbox.py) uses the same factory.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

# sqlite authorizer actions that are safe for a read-only caller.
ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}

Authorizer = Callable[[int, object, object, object, object], int]


def make_authorizer(violations: list[str] | None = None) -> Authorizer:
    """Build an sqlite3 authorizer callback.

    `violations`, if given, receives a detail string for every denied action
    (mirrors `SnapshotSandbox.log.violations`'s original behavior). Pass
    `None` when the caller has nowhere to log violations and only cares
    about the deny itself.
    """

    def _authorizer(action: int, arg1, arg2, db_name, trigger) -> int:
        if action in ALLOWED_ACTIONS:
            return sqlite3.SQLITE_OK
        if violations is not None:
            violations.append(f"action={action} arg1={arg1!r} arg2={arg2!r}")
        return sqlite3.SQLITE_DENY

    return _authorizer
