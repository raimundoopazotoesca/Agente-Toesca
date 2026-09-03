"""Shared read-only sqlite3 authorizer, used by every SqlSandbox implementation.

Extracted (Stage A2 of the Alpha v0.1 build) from the `_authorizer` method
that lived on `eval.benchmark.snapshot.SnapshotSandbox`. There is exactly one
copy of this logic in the codebase: `SnapshotSandbox` now imports
`make_authorizer` from here instead of defining its own bound method, and
`LiveReadOnlySandbox` (live_sandbox.py) uses the same factory.

A3.1b: beyond the action-class check, this now enforces object- and
function-level allowlists:

  - `SQLITE_READ` (reading a table/view column) is allowed only when the
    object being read (`arg1`) is `tools.db.sql_surface.is_queryable`. This
    is the correct enforcement point empirically: `arg1` is the table/view
    name being read, and reading a view also emits `SQLITE_READ` for every
    backing object in its dependency chain -- so a view whose backing
    objects fall outside the registry is correctly denied via those calls.
  - `SQLITE_FUNCTION` is allowed only when `arg2` (the lowercase function
    name -- NOT `arg1`, confirmed empirically) normalizes into a fixed
    19-entry allowlist. This includes two entries added after an audit of
    every SQL statement that actually runs through a `guard=True` connection
    (schema84 views, `tools/datasets/catalog_v1.yaml`'s governed dataset
    `source_sql`, `GovernedDatasetExecutor`/`AnalyticsExecutor`-generated
    SQL, and the RunSqlAction/benchmark workload): `INSTR` (used by the
    `rent_roll` governed dataset's `source_sql` to parse an office floor
    label) and `GOVERNED_JLL_FLOOR` (a custom Python function registered
    per-connection via `conn.create_function("governed_jll_floor", 1, ...)`
    in `tools/datasets/executor.py` -- SQLite still routes a call to it
    through `SQLITE_FUNCTION` with `arg2="governed_jll_floor"` exactly like
    any builtin, so it is allowlisted the same way; the authorizer only
    decides whether SQLite's attempt to call it is *permitted*, it does not
    register the function itself).
  - `SQLITE_SELECT` and `SQLITE_RECURSIVE` carry no object identity and are
    allowed unconditionally (recursive CTEs are otherwise ordinary reads,
    already gated by their own `SQLITE_READ` calls).

`sql_surface` is imported here directly -- no local/duplicated object list.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from tools.db import sql_surface

# Function names (normalized to uppercase) allowed through SQLITE_FUNCTION.
# Frozen 19-entry set (17 original + INSTR + GOVERNED_JLL_FLOOR, added after
# an audit of the actual guarded-runtime SQL -- see module docstring) -- do
# not extend further without re-auditing the guarded surface.
ALLOWED_FUNCTIONS = frozenset({
    "SUM", "AVG", "COUNT", "MIN", "MAX", "ROUND", "ABS", "UPPER", "LOWER",
    "SUBSTR", "DATE", "STRFTIME", "COALESCE", "JSON_EXTRACT", "NULLIF",
    "LIKE", "TRIM", "INSTR", "GOVERNED_JLL_FLOOR",
})

Authorizer = Callable[[int, object, object, object, object], int]


def make_authorizer(violations: list[str] | None = None) -> Authorizer:
    """Build an sqlite3 authorizer callback.

    `violations`, if given, receives a detail string for every denied action
    (mirrors `SnapshotSandbox.log.violations`'s original behavior). Pass
    `None` when the caller has nowhere to log violations and only cares
    about the deny itself.
    """

    def _authorizer(action: int, arg1, arg2, db_name, trigger) -> int:
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if sql_surface.is_queryable(arg1):
                return sqlite3.SQLITE_OK
        elif action == sqlite3.SQLITE_FUNCTION:
            fname = (arg2 or "").upper()
            if fname in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
        if violations is not None:
            violations.append(f"action={action} arg1={arg1!r} arg2={arg2!r}")
        return sqlite3.SQLITE_DENY

    return _authorizer
