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
from pathlib import Path
from typing import Protocol

from tools.analyst_runtime.transport import ToolRequest, ToolResult, ToolSpec
from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError

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
            return ToolResult(call_id=request.call_id, ok=False, content=json.dumps({"error": error}, ensure_ascii=False), trace=_sql_trace(query, error=error))
        sql = query.strip().rstrip(";")
        if not re.search(r"\blimit\b\s+\d+", sql, re.IGNORECASE):
            sql = f"{sql} LIMIT {MAX_ROWS_RETURNED}"
        conn = self.sandbox.connect(guard=True)
        try:
            cur = conn.execute(sql)
            cols = [d[0] for d in cur.description or []]
            rows = [list(r) for r in cur.fetchmany(MAX_ROWS_RETURNED)]
            return ToolResult(call_id=request.call_id, ok=True, content=format_query_result(cols, rows), trace=_sql_trace(query, row_count=len(rows)))
        except Exception as exc:  # noqa: BLE001 -- surfaced to the model as a tool error, not raised
            return ToolResult(call_id=request.call_id, ok=False, content=json.dumps({"error": str(exc)}, ensure_ascii=False), trace=_sql_trace(query, error=str(exc)))
        finally:
            conn.close()


@dataclass
class AnalyticsQueryAction:
    """Execute one governed metric request; selection remains the model's job."""

    db_path: Path
    name: str = "analytics_query"

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(self.name, "Consulta métricas gobernadas disponibles en el catálogo con validación de grano, dimensiones y fuente.", {
            "type": "object", "additionalProperties": False,
            "properties": {
                "metric": {"type": "string", "enum": ["vacancia_pct_fondo", "vacancia_fisica_pct_activo", "m2_vacantes"], "description": "Identidad exacta de la métrica gobernada."},
                "funds": {"type": "array", "items": {"type": "string"}, "description": "Fondos en el alcance; requerido para métricas de fondo."},
                "assets": {"type": "array", "items": {"type": "string"}, "description": "Activos en el alcance; requerido para métricas de activo."},
                "period": {"type": "string", "description": "Mes inicial en formato YYYY-MM."},
                "period_end": {"type": "string", "description": "Mes final inclusivo YYYY-MM para una serie de la misma métrica."},
                "group_by": {"type": "string", "enum": ["asset"], "description": "Dimensión permitida para desglosar la métrica."},
                "order_by": {"type": "string", "enum": ["value_desc", "value_asc"], "description": "Orden de los valores devueltos."},
                "limit": {"type": "integer", "minimum": 1, "description": "Máximo de filas devueltas."},
            },
            "required": ["metric", "period"],
        })

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            result = AnalyticsExecutor(self.db_path).execute(_analytics_request(request.arguments))
            payload = {"catalog_version": result.catalog_version, "result_kind": result.result_kind, "rows": [row.__dict__ for row in result.rows]}
            return ToolResult(request.call_id, True, json.dumps(payload, ensure_ascii=False, default=str), trace=_analytics_trace(request.arguments, payload))
        except SemanticQueryError as exc:
            payload = {"error_type": "semantic_query_error", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False), trace=_analytics_trace(request.arguments, payload))
        except (KeyError, TypeError, ValueError) as exc:
            payload = {"error_type": "invalid_request", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False), trace=_analytics_trace(request.arguments, payload))


_ANALYTICS_ARGUMENT_FIELDS = frozenset({"metric", "funds", "assets", "period", "period_end", "group_by", "order_by", "limit"})


def _analytics_request(arguments: dict[str, object]) -> AnalyticsQueryRequest:
    unknown = sorted(set(arguments) - _ANALYTICS_ARGUMENT_FIELDS)
    if unknown:
        raise ValueError(f"unknown analytics_query fields: {', '.join(unknown)}")
    return AnalyticsQueryRequest(
        metric=_required_string(arguments, "metric"),
        funds=_string_array(arguments, "funds"),
        assets=_string_array(arguments, "assets"),
        period=_required_string(arguments, "period"),
        period_end=_optional_string(arguments, "period_end"),
        group_by=_optional_string(arguments, "group_by"),
        order_by=_optional_string(arguments, "order_by"),
        limit=_optional_positive_int(arguments, "limit"),
    )


def _required_string(arguments: dict[str, object], name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(arguments: dict[str, object], name: str) -> str | None:
    value = arguments.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _string_array(arguments: dict[str, object], name: str) -> tuple[str, ...]:
    value = arguments.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be an array of strings")
    return tuple(value)


def _optional_positive_int(arguments: dict[str, object], name: str) -> int | None:
    value = arguments.get(name)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
        raise ValueError(f"{name} must be a positive integer")
    return value


def _analytics_trace(arguments: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    allowed = _ANALYTICS_ARGUMENT_FIELDS
    trace: dict[str, object] = {"arguments": {name: arguments[name] for name in allowed if name in arguments}}
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        trace["unknown_fields"] = unknown
    if "error_type" in payload:
        trace["error"] = {"error_type": payload["error_type"], "message": payload.get("error", "")}
        return trace
    rows = payload.get("rows", [])
    first = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    ingest_run_ids = sorted({
        row["provenance"]["ingest_run_id"]
        for row in rows if isinstance(row, dict) and isinstance(row.get("provenance"), dict)
        and isinstance(row["provenance"].get("ingest_run_id"), int)
    }) if isinstance(rows, list) else []
    trace["result"] = {
        "metric_key": first.get("metric_key"),
        "source_kind": first.get("source_kind"),
        "catalog_version": payload.get("catalog_version"),
        "row_count": len(rows) if isinstance(rows, list) else 0,
        "provenance_ingest_run_ids": ingest_run_ids,
    }
    return trace


def _sql_trace(query: object, row_count: int | None = None, error: str | None = None) -> dict[str, object]:
    trace: dict[str, object] = {"arguments": {"query": query}}
    if error is None:
        trace["result"] = {"row_count": row_count}
    else:
        trace["error"] = {"error_type": "sql_error", "message": error}
    return trace


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
                trace={"error": {"error_type": "unknown_action", "message": f"unknown action: {request.name}"}},
            )
        return action.execute(request)
