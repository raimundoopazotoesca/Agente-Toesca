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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

from tools.analyst_runtime.transport import ToolRequest, ToolResult, ToolSpec
from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError
from tools.analytics.capabilities import capability_metric_keys
from tools.analytics.catalog import load_metric_catalog
from tools.schema_discovery import (
    DEFAULT_SCHEMA_SEARCH_LIMIT,
    MAX_SCHEMA_SEARCH_LIMIT,
    SchemaIntrospector,
    SQLiteSchemaIntrospector,
)
from tools.entities.catalog import ENTITY_TYPES
from tools.entities.resolver import EntityResolver

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
class SchemaSearchAction:
    """Expose normalized, read-only schema metadata to Alpha exploration."""

    db_path: Path
    introspector: SchemaIntrospector | None = None
    name: str = "schema_search"
    description: str = (
        "Searches read-only database metadata for relevant tables and views, "
        "returning structured columns and verified relationships to support raw data exploration."
    )

    def __post_init__(self) -> None:
        if self.introspector is None:
            self.introspector = SQLiteSchemaIntrospector(self.db_path)

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Metadata search terms for tables, views, columns, and verified relationships."},
                "limit": {"type": ["integer", "null"], "minimum": 1, "description": "Maximum metadata objects returned; use null for the default."},
            },
            "required": ["query", "limit"],
        })

    def execute(self, request: ToolRequest) -> ToolResult:
        started = time.monotonic()
        requested_limit = request.arguments.get("limit")
        effective_limit: int | None = None
        try:
            unknown = sorted(set(request.arguments) - {"query", "limit"})
            if unknown:
                raise ValueError(f"unknown schema_search fields: {', '.join(unknown)}")
            query = _required_string(request.arguments, "query")
            limit = _optional_positive_int(request.arguments, "limit")
            effective_limit = min(limit, MAX_SCHEMA_SEARCH_LIMIT) if limit is not None else DEFAULT_SCHEMA_SEARCH_LIMIT
            assert self.introspector is not None
            result = self.introspector.search(query, effective_limit)
            payload = result.as_dict()
            trace = _schema_trace(query, requested_limit, effective_limit, result.dialect, result.metadata_version, [obj.name for obj in result.objects], True, started, candidate_scores=result.candidate_scores)
            return ToolResult(request.call_id, True, json.dumps(payload, ensure_ascii=False), trace=trace)
        except (KeyError, TypeError, ValueError) as exc:
            payload = {"error_type": "invalid_request", "error": str(exc)}
            trace = _schema_trace(request.arguments.get("query"), requested_limit, effective_limit, None, None, [], False, started, "invalid_request", str(exc))
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False), trace=trace)
        except Exception as exc:  # noqa: BLE001 -- tool failures are reported, never raised through the loop
            payload = {"error_type": "schema_search_error", "error": str(exc)}
            trace = _schema_trace(request.arguments.get("query"), requested_limit, effective_limit, None, None, [], False, started, "schema_search_error", str(exc))
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False), trace=trace)

@dataclass
class ResolveEntityAction:
    db_path: Path
    name: str = "resolve_entity"
    description: str = "Resolves human references to canonical Toesca entities and returns canonical keys or explicit ambiguity using governed dimension data."
    def tool_spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, {"type":"object","additionalProperties":False,"properties":{"query":{"type":"string"},"entity_types":{"type":"array","items":{"type":"string","enum":list(ENTITY_TYPES)}},"fund":{"type":["string","null"]}},"required":["query","entity_types","fund"]})
    def execute(self, request: ToolRequest) -> ToolResult:
        started=time.monotonic()
        try:
            if set(request.arguments)!={"query","entity_types","fund"}: raise ValueError("invalid resolve_entity fields")
            query=_required_string(request.arguments,"query"); types=request.arguments["entity_types"]; fund=request.arguments["fund"]
            if not isinstance(types,list) or not types or any(t not in ENTITY_TYPES for t in types): raise ValueError("entity_types must contain supported entity types")
            if fund is not None and not isinstance(fund,str): raise ValueError("fund must be a canonical fund key or null")
            result=EntityResolver(self.db_path).resolve(query,tuple(types),fund); payload=result.as_dict()
            trace={"tool_name":self.name,"query":query,"requested_entity_types":types,"fund":fund,"status":result.status,"candidates":[{"entity_key":c.entity_key,"canonical_name":c.canonical_name,"score":c.score,"match_kind":c.match_kind} for c in result.candidates],"success":True,"duration_ms":(time.monotonic()-started)*1000}
            return ToolResult(request.call_id,True,json.dumps(payload,ensure_ascii=False),trace=trace)
        except (KeyError,TypeError,ValueError) as exc:
            return ToolResult(request.call_id,False,json.dumps({"error_type":"invalid_request","error":str(exc)},ensure_ascii=False),trace={"tool_name":self.name,"success":False,"error":{"error_type":"invalid_request","message":str(exc)},"duration_ms":(time.monotonic()-started)*1000})
        except Exception as exc:  # noqa: BLE001 -- tool failures are reported, never raised through the loop
            payload = {"error_type": "resolve_entity_error", "error": str(exc)}
            trace = {"tool_name":self.name,"success":False,"error":{"error_type":"resolve_entity_error","message":str(exc)},"duration_ms":(time.monotonic()-started)*1000}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False), trace=trace)


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


def _optional_positive_int(arguments: dict[str, object], name: str) -> int | None:
    value = arguments.get(name)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
        raise ValueError(f"{name} must be a positive integer")
    return value


def _sql_trace(query: object, row_count: int | None = None, error: str | None = None) -> dict[str, object]:
    trace: dict[str, object] = {"arguments": {"query": query}}
    if error is None:
        trace["result"] = {"row_count": row_count}
    else:
        trace["error"] = {"error_type": "sql_error", "message": error}
    return trace


def _schema_trace(query: object, requested_limit: object, effective_limit: int | None, dialect: str | None, metadata_version: str | None, candidate_names: list[str], success: bool, started: float, error_type: str | None = None, error: str | None = None, candidate_scores: dict[str, int] | None = None) -> dict[str, object]:
    trace: dict[str, object] = {
        "tool_name": "schema_search", "query": query, "requested_limit": requested_limit,
        "effective_limit": effective_limit, "dialect": dialect, "metadata_version": metadata_version,
        "candidate_names": candidate_names, "object_count": len(candidate_names), "success": success,
        "duration_ms": (time.monotonic() - started) * 1000,
    }
    if candidate_scores is not None:
        trace["candidate_scores"] = candidate_scores
    if error_type is not None:
        trace["error"] = {"error_type": error_type, "message": error or ""}
    return trace


@dataclass
class _AnalyticsCapabilityAction:
    """Catalog-derived action surface; execution remains in AnalyticsExecutor."""

    db_path: Path
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    capability: ClassVar[str] = ""
    scope_field: ClassVar[str] = ""
    breakdown: ClassVar[bool] = False

    def tool_spec(self) -> ToolSpec:
        properties: dict[str, object] = {
            "metric": {
                "type": "string",
                "enum": list(self._metric_keys()),
                "description": "Exact governed metric identity available for this operation.",
            },
            self.scope_field: {"type": "string", "description": f"{self.scope_field.title()} scope for this operation."},
            "period": {"type": "string", "description": "Initial month in YYYY-MM format."},
            "period_end": {"type": ["string", "null"], "description": "Optional inclusive final month in YYYY-MM format; use null for a point lookup."},
        }
        if self.breakdown:
            properties.update({
                "order_by": {"type": ["string", "null"], "enum": ["value_desc", "value_asc", None], "description": "Ordering for comparable metric values; use null for the native order."},
                "limit": {"type": ["integer", "null"], "minimum": 1, "description": "Maximum number of rows returned; use null for the capability default."},
            })
        return ToolSpec(self.name, self.description, {
            "type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties),
        })

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            analytics_request, scope = self._request(request.arguments)
            result = AnalyticsExecutor(self.db_path).execute(analytics_request)
            payload = {
                "catalog_version": result.catalog_version,
                "result_kind": result.result_kind,
                "rows": [row.__dict__ for row in result.rows],
            }
            return ToolResult(request.call_id, True, json.dumps(payload, ensure_ascii=False, default=str),
                              trace=_capability_trace(request.arguments, scope, payload, self._allowed_fields()))
        except SemanticQueryError as exc:
            payload = {"error_type": "semantic_query_error", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False),
                              trace=_capability_trace(request.arguments, {}, payload, self._allowed_fields()))
        except (KeyError, TypeError, ValueError) as exc:
            payload = {"error_type": "invalid_request", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False),
                              trace=_capability_trace(request.arguments, {}, payload, self._allowed_fields()))

    def _metric_keys(self) -> tuple[str, ...]:
        return capability_metric_keys(load_metric_catalog())[self.capability]

    def _allowed_fields(self) -> frozenset[str]:
        fields = {"metric", self.scope_field, "period", "period_end"}
        if self.breakdown:
            fields.update({"order_by", "limit"})
        return frozenset(fields)

    def _request(self, arguments: dict[str, object]) -> tuple[AnalyticsQueryRequest, dict[str, str]]:
        unknown = sorted(set(arguments) - self._allowed_fields())
        if unknown:
            raise ValueError(f"unknown {self.name} fields: {', '.join(unknown)}")
        metric = _required_string(arguments, "metric")
        if metric not in self._metric_keys():
            raise ValueError(f"metric is not available for {self.name}: {metric}")
        scope_value = _required_string(arguments, self.scope_field)
        period = _required_string(arguments, "period")
        period_end = _optional_string(arguments, "period_end")
        if self.scope_field == "fund":
            funds, assets, scope = (scope_value,), (), {"fund": scope_value}
        else:
            funds, assets, scope = (), (scope_value,), {"asset": scope_value}
        order_by = _optional_string(arguments, "order_by") if self.breakdown else None
        limit = _optional_positive_int(arguments, "limit") if self.breakdown else None
        return AnalyticsQueryRequest(
            metric=metric, funds=funds, assets=assets, period=period, period_end=period_end,
            group_by="asset" if self.breakdown else None, order_by=order_by, limit=limit,
        ), scope


class AnalyticsLookupFundAction(_AnalyticsCapabilityAction):
    name = "analytics_lookup_fund"
    description = "Returns governed fund-level metric values for a fund and point or period range, validated against the metric catalog."
    capability = "fund_lookup"
    scope_field = "fund"
    breakdown = False


class AnalyticsLookupAssetAction(_AnalyticsCapabilityAction):
    name = "analytics_lookup_asset"
    description = "Returns governed asset-level metric values for an asset and point or period range, validated against the metric catalog."
    capability = "asset_lookup"
    scope_field = "asset"
    breakdown = False


class AnalyticsBreakdownAssetAction(_AnalyticsCapabilityAction):
    name = "analytics_breakdown_asset"
    description = "Returns governed metric breakdowns across comparable assets for a fund and period, with optional ordering and limit, validated against the metric catalog."
    capability = "asset_breakdown"
    scope_field = "fund"
    breakdown = True


def _capability_trace(arguments: dict[str, object], scope: dict[str, str], payload: dict[str, object], allowed: frozenset[str]) -> dict[str, object]:
    trace: dict[str, object] = {"arguments": {name: arguments[name] for name in allowed if name in arguments}}
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        trace["unknown_fields"] = unknown
    if scope:
        trace["scope"] = scope
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
