"""F4 Stage 3: generic action dispatch behind the ActionExecutor seam.

Moved from eval/benchmark/adapters/actions.py (Stage A1 of the Alpha v0.1
build). The only substantive change from the original is the sandbox
dependency: instead of importing the benchmark-only `SnapshotSandbox`
concretely, `RunSqlAction.sandbox` is typed against the `SqlSandbox`
Protocol defined here. `SnapshotSandbox` (eval/benchmark/snapshot.py) and
`LiveReadOnlySandbox` (live_sandbox.py) both structurally satisfy it --
duck typing, zero coupling back to the benchmark harness.

`ActionRegistry` does exactly one job -- given a ToolRequest, find the
Action with that name and run it, or return a clear error if none exists.
No lifecycle framework, no plugin loader, no dependency injection, no
hooks/middleware, no action categories/confidence/priorities.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Protocol

from tools.analyst_runtime.transport import ToolRequest, ToolResult, ToolSpec

MAX_ROWS_RETURNED = 50

_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace)\b",
    re.IGNORECASE,
)


class SqlSandbox(Protocol):
    """Anything that can hand out a guarded, read-only sqlite3 connection.

    `SnapshotSandbox` (pinned benchmark snapshot) and `LiveReadOnlySandbox`
    (live production DB) both satisfy this structurally -- RunSqlAction
    depends on the Protocol, never on either concrete class.
    """

    def connect(self, guard: bool = True) -> sqlite3.Connection: ...


def validate_sql(sql: str) -> str | None:
    """None if safe to attempt; an error string otherwise. Byte-for-byte the
    same check Stage 1/2 used (moved here, not rewritten) -- this is a cheap
    pre-filter for a better error message back to the model; the sandbox's
    own authorizer is the actual enforcement layer regardless."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        return "Query vacia."
    if ";" in s:
        return "Solo se permite una sentencia SQL."
    head = s.split(None, 1)[0].lower()
    if head not in {"select", "with"}:
        return "Solo se permiten sentencias SELECT o WITH."
    if _FORBIDDEN_RE.search(s):
        return "La consulta contiene una operacion no permitida (solo lectura)."
    return None


def format_query_result(columns: list[str], rows: list[list]) -> str:
    truncated = rows[:MAX_ROWS_RETURNED]
    payload = {
        "columns": columns,
        "rows": truncated,
        "row_count": len(rows),
        "truncated": len(rows) > len(truncated),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


class Action(Protocol):
    """One invocable capability. NOT another reasoning loop -- an Action has
    no memory, no multi-step planning of its own, no opinion about whether
    it should be called. It translates one ToolRequest into one ToolResult.
    """

    name: str

    def tool_spec(self) -> ToolSpec: ...

    def execute(self, request: ToolRequest) -> ToolResult: ...


@dataclass
class RunSqlAction:
    """Reuses the exact same security surface as its predecessor implementations,
    not reimplemented: validate_sql, the guarded read-only sandbox connection
    (shared authorizer, sqlite_guard.py), implicit LIMIT injection, and
    format_query_result.
    """

    sandbox: SqlSandbox
    name: str = "run_sql"
    description: str = (
        "Run one read-only SELECT statement against the Toesca real-estate "
        "database and get back columns + rows. Use it as many times as "
        "needed before answering -- one query per call."
    )

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A single SELECT (or WITH ... SELECT) statement. No semicolons, no writes.",
                    }
                },
                "required": ["query"],
            },
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        query = request.arguments.get("query", "")
        error = validate_sql(query)
        if error:
            return ToolResult(call_id=request.call_id, ok=False, content=json.dumps({"error": error}, ensure_ascii=False))
        sql = query.strip().rstrip(";")
        if not re.search(r"\blimit\b\s+\d+", sql, re.IGNORECASE):
            sql = f"{sql} LIMIT {MAX_ROWS_RETURNED}"
        conn = self.sandbox.connect(guard=True)
        try:
            cur = conn.execute(sql)
            cols = [d[0] for d in cur.description or []]
            rows = [list(r) for r in cur.fetchmany(MAX_ROWS_RETURNED)]
            return ToolResult(call_id=request.call_id, ok=True, content=format_query_result(cols, rows))
        except Exception as exc:  # noqa: BLE001 -- surfaced to the model as a tool error, not raised
            return ToolResult(call_id=request.call_id, ok=False, content=json.dumps({"error": str(exc)}, ensure_ascii=False))
        finally:
            conn.close()


@dataclass
class ActionRegistry:
    """AnalystLoop's ActionExecutor, generalized to N actions."""

    actions: list[Action] = field(default_factory=list)
    _by_name: dict[str, Action] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_name = {}
        for action in self.actions:
            if action.name in self._by_name:
                raise ValueError(f"duplicate action name: {action.name!r}")
            self._by_name[action.name] = action

    def tool_specs(self) -> list[ToolSpec]:
        return [action.tool_spec() for action in self.actions]

    def execute(self, request: ToolRequest) -> ToolResult:
        action = self._by_name.get(request.name)
        if action is None:
            return ToolResult(
                call_id=request.call_id, ok=False,
                content=json.dumps({"error": f"unknown action: {request.name}"}, ensure_ascii=False),
            )
        return action.execute(request)
