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

from tools.analyst_runtime.transport import ToolEvidence, ToolRequest, ToolResult, ToolSpec
from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError
from tools.analytics.capabilities import capability_metric_keys, metric_period_bounds
from tools.analytics.catalog import load_metric_catalog
from tools.analytics.account_concepts import AccountConceptCatalog, AccountQuery, AccountQueryError, AccountQueryExecutor
from tools.schema_discovery import (
    DEFAULT_SCHEMA_SEARCH_LIMIT,
    MAX_SCHEMA_SEARCH_LIMIT,
    SchemaIntrospector,
    SQLiteSchemaIntrospector,
)
from tools.entities.catalog import ENTITY_TYPES
from tools.entities.resolver import EntityResolver
from tools.entities.canonical_scope import CanonicalScopeValidator, expected_asset_universe

MAX_ROWS_RETURNED = 50

# Fixed, metric-agnostic half of every governed capability description; the
# rest is generated from the Metric Catalog (see `_description`).
_GOVERNED_AUTHORITY_NOTE = (
    "Es la vía autoritativa para estas métricas: úsala en vez de reconstruirlas "
    "con SQL crudo o de buscarlas en el esquema."
)

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
            control = None
            if result.status != "resolved":
                control = {
                    "kind": "clarification_required",
                    "reason": result.status,
                    "entity_query": query,
                    "resolution_status": result.status,
                    "candidates": [candidate.as_dict() for candidate in result.candidates],
                }
                trace.update({"resolution_status": result.status, "clarification_required": True})
            else:
                trace["resolution_status"] = "resolved"
            return ToolResult(request.call_id,True,json.dumps(payload,ensure_ascii=False),trace=trace,control=control)
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


def _required_key_list(arguments: dict[str, object], name: str) -> list[str]:
    value = arguments.get(name)
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must be a non-empty list of canonical keys")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not repeat a canonical key")
    return list(value)


def _optional_key_list(arguments: dict[str, object], name: str) -> list[str]:
    if arguments.get(name) is None:
        return []
    return _required_key_list(arguments, name)


def _validate_subset_membership(db_path: Path, fund_key: str, assets: tuple[str, ...], period: str) -> None:
    """Every explicitly requested asset must belong to the fund and be
    temporally applicable at `period` -- same rule as expected_asset_universe.
    An asset that belongs but simply has no KPI row is NOT rejected here: it
    stays in the expected universe so coverage reports `partial`."""
    if not CanonicalScopeValidator(db_path).validate_fund(fund_key).valid:
        raise SemanticQueryError(f"unknown canonical fund: {fund_key}")
    universe = expected_asset_universe(db_path, fund_key, period)
    if universe.status != "determined":
        raise SemanticQueryError(f"asset universe is undetermined for fund: {fund_key}")
    outside = sorted(set(assets) - universe.eligible_keys)
    if outside:
        raise SemanticQueryError(
            f"assets not applicable to fund {fund_key} at {period}: {', '.join(outside)}"
        )


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
    catalog_path: Path | None = None
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    capability: ClassVar[str] = ""
    scope_field: ClassVar[str] = ""   # "fund" | "assets"
    breakdown: ClassVar[bool] = False
    subset: ClassVar[bool] = False    # fund-scoped operations may take an explicit asset subset

    def tool_spec(self) -> ToolSpec:
        properties: dict[str, object] = {
            "metric": {
                "type": "string",
                "enum": list(self._metric_keys()),
                "description": "Exact governed metric identity available for this operation.",
            },
            "period": {"type": "string", "description": "Initial month in YYYY-MM format."},
            "period_end": {"type": ["string", "null"], "description": "Optional inclusive final month in YYYY-MM format; use null for a point lookup."},
            "aggregation": {"type": ["string", "null"], "enum": ["sum", "avg", "last", None], "description": "Optional temporal aggregation; it is accepted only when the metric contract permits it."},
        }
        if self.scope_field == "fund":
            properties["fund"] = {"type": "string", "description": "Canonical fund key scoping this operation."}
        else:
            properties["assets"] = {
                "type": "array", "items": {"type": "string"}, "minItems": 1,
                "description": "One or more canonical asset keys to look up.",
            }
        if self.subset:
            properties["assets"] = {
                "type": ["array", "null"], "items": {"type": "string"}, "minItems": 1,
                "description": "Optional explicit subset of canonical asset keys within the fund; use null to cover the whole fund.",
            }
        if self.breakdown:
            properties.update({
                "order_by": {"type": ["string", "null"], "enum": ["value_desc", "value_asc", None], "description": "Ordering for comparable metric values; use null for the native order."},
                "limit": {"type": ["integer", "null"], "minimum": 1, "description": "Maximum number of rows returned; use null for the capability default."},
            })
        return ToolSpec(self.name, self._description(), {
            "type": "object", "additionalProperties": False, "properties": properties,
            "required": [name for name in properties if name != "aggregation"],
        })

    def _description(self) -> str:
        """Name the metrics this capability covers, straight from the catalog,
        each with the months actually observed for it.

        Everything after the fixed prefix is DERIVED: adding a metric to the
        catalog makes it appear here with no prompt or code change. Without
        this the metrics are discoverable only inside a JSON enum of opaque
        keys and with no hint of which `period` is answerable, so the model
        falls back to raw exploration for questions the governed path already
        answers -- and a raw reconstruction carries no canonical authority."""
        catalog = self._catalog().metrics
        available = "; ".join(self._metric_affordance(catalog[key])
                              for key in self._metric_keys() if key in catalog)
        return (f"{self.description} {_GOVERNED_AUTHORITY_NOTE} "
                f"Métricas disponibles: {available}.")

    def _metric_affordance(self, metric) -> str:
        bounds = metric_period_bounds(self.db_path, metric)
        period_hint = f", períodos {bounds[0]}..{bounds[1]}" if bounds else ""
        return f"{metric.display_name} ({metric.key}{period_hint})"

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            analytics_request, scope = self._request(request.arguments)
            result = AnalyticsExecutor(self.db_path).execute(analytics_request)
            payload = {
                # The evidence_id must be visible to the model: a structured
                # claim can only bind to evidence it can name.
                "evidence_id": request.call_id,
                "catalog_version": result.catalog_version,
                "result_kind": result.result_kind,
                "rows": [row.__dict__ for row in result.rows],
            }
            evidence = None
            if result.result_kind == "scalar" and len(result.rows) == 1:
                row = result.rows[0]
                evidence = ToolEvidence(
                    evidence_id=request.call_id,
                    evidence_class="canonical_metric",
                    source={"tool_name": self.name, "source_kind": row.source_kind},
                    scope=scope,
                    semantic_contract={"metric_key": row.metric_key,
                                       "aggregation": request.arguments.get("aggregation")},
                    provenance=row.provenance,
                    facts=({"metric_key": row.metric_key, "value": row.value, "unit": row.unit,
                            "entity_id": row.entity_id, "period": row.period},),
                )
            elif result.rows:
                # A multi-row *scalar* result is a time series over one entity,
                # not an entity universe: it becomes governed_dataset evidence
                # marked `period_range` so coverage_guard never frames it as
                # partial/complete over assets. Per-row identity stays
                # (entity_id, period) in either case.
                period_range = result.result_kind == "scalar"
                coverage = (_period_range_coverage(result.rows) if period_range
                            else _governed_dataset_coverage(self.db_path, scope, request.arguments, result.rows))
                evidence = ToolEvidence(
                    evidence_id=request.call_id,
                    evidence_class="governed_dataset",
                    source={"tool_name": self.name, "source_kind": result.rows[0].source_kind},
                    scope=scope,
                    semantic_contract={"metric_key": result.rows[0].metric_key,
                                       "entity_grain": result.rows[0].entity_type,
                                       "period_grain": "month",
                                       "universe_kind": coverage["universe_kind"],
                                       "aggregation": request.arguments.get("aggregation")},
                    provenance={"ingest_run_ids": sorted({
                        r.provenance.get("ingest_run_id") for r in result.rows
                        if isinstance(r.provenance, dict) and isinstance(r.provenance.get("ingest_run_id"), int)
                    })},
                    coverage=coverage,
                    facts=tuple({"metric_key": r.metric_key, "value": r.value, "unit": r.unit,
                                 "entity_id": r.entity_id, "period": r.period} for r in result.rows),
                )
            return ToolResult(request.call_id, True, json.dumps(payload, ensure_ascii=False, default=str),
                              trace=_capability_trace(request.arguments, scope, payload, self._allowed_fields()), evidence=evidence)
        except SemanticQueryError as exc:
            if exc.code != "invalid_aggregation":
                payload = {"error_type": "semantic_query_error", "error": str(exc)}
                return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False),
                                  trace=_capability_trace(request.arguments, {}, payload, self._allowed_fields()))
            rejection = {"code": exc.code, **exc.metadata}
            payload = {"error_type": "semantic_rejection", "error": str(exc), "semantic_rejection": rejection}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False),
                              trace={**_capability_trace(request.arguments, {}, payload, self._allowed_fields()),
                                     "semantic_rejection": rejection},
                              control={"kind": "semantic_rejection", **rejection})
        except (KeyError, TypeError, ValueError) as exc:
            payload = {"error_type": "invalid_request", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False),
                              trace=_capability_trace(request.arguments, {}, payload, self._allowed_fields()))

    def _catalog(self):
        return load_metric_catalog(self.catalog_path)

    def _metric_keys(self) -> tuple[str, ...]:
        return capability_metric_keys(self._catalog())[self.capability]

    def _allowed_fields(self) -> frozenset[str]:
        fields = {"metric", self.scope_field, "period", "period_end", "aggregation"}
        if self.subset:
            fields.add("assets")
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
        period = _required_string(arguments, "period")
        period_end = _optional_string(arguments, "period_end")
        aggregation = _optional_string(arguments, "aggregation")
        universe_period = period_end or period
        if self.scope_field == "fund":
            fund = _required_string(arguments, "fund")
            assets = tuple(_optional_key_list(arguments, "assets")) if self.subset else ()
            if assets:
                _validate_subset_membership(self.db_path, fund, assets, universe_period)
            funds, scope = (fund,), {"fund": fund}
        else:
            assets = tuple(_required_key_list(arguments, "assets"))
            funds, scope = (), ({"asset": assets[0]} if len(assets) == 1 else {"assets": list(assets)})
        order_by = _optional_string(arguments, "order_by") if self.breakdown else None
        limit = _optional_positive_int(arguments, "limit") if self.breakdown else None
        # An explicit multi-asset lookup is a breakdown over an explicit
        # subset, not a scalar: it must carry per-entity identity.
        group_by = "asset" if (self.breakdown or (self.scope_field == "assets" and len(assets) > 1)) else None
        return AnalyticsQueryRequest(
            metric=metric, funds=funds, assets=assets, period=period, period_end=period_end,
            group_by=group_by, order_by=order_by, limit=limit, aggregation=aggregation,
        ), scope


class AnalyticsLookupFundAction(_AnalyticsCapabilityAction):
    name = "analytics_lookup_fund"
    description = "Returns governed fund-level metric values for a fund and point or period range, validated against the metric catalog."
    capability = "fund_lookup"
    scope_field = "fund"
    breakdown = False


class AnalyticsLookupAssetAction(_AnalyticsCapabilityAction):
    name = "analytics_lookup_asset"
    description = "Returns governed asset-level metric values for one or more canonical assets and a point or period range, validated against the metric catalog."
    capability = "asset_lookup"
    scope_field = "assets"
    breakdown = False


class AnalyticsBreakdownAssetAction(_AnalyticsCapabilityAction):
    name = "analytics_breakdown_asset"
    description = "Returns governed metric breakdowns and rankings across the assets of a fund for a period, optionally restricted to an explicit asset subset, with optional ordering and limit, validated against the metric catalog."
    capability = "asset_breakdown"
    scope_field = "fund"
    breakdown = True
    subset = True


@dataclass
class AnalyticsAccountQueryAction:
    """One generic governed capability for catalog-defined account concepts."""
    db_path: Path
    catalog: AccountConceptCatalog | None = None
    name: str = "analytics_account_query"

    def __post_init__(self) -> None:
        self.catalog = self.catalog or AccountConceptCatalog.load()

    def tool_spec(self) -> ToolSpec:
        assert self.catalog is not None
        concepts = "; ".join(f"{item.display_name} ({item.concept_id}; aliases: {', '.join(item.aliases)})" for item in self.catalog._concepts.values())
        return ToolSpec(self.name, f"Consulta conceptos contables canónicos a nivel de activo mediante mappings exactos gobernados. Para gastos, pagos, contribuciones, seguros u otras cuentas disponibles, úsala en vez de SQL crudo. La base es ER/devengado: no prueba pago de caja. Conceptos disponibles: {concepts}.", {"type": "object", "additionalProperties": False, "properties": {
            "concept": {"type": "string", "enum": sorted(self.catalog._concepts)}, "entity": {"type": "string"},
            "entity_type": {"type": "string", "enum": ["asset"]}, "period": {"type": "string"},
            "period_end": {"type": ["string", "null"]}, "aggregation": {"type": ["string", "null"], "enum": ["sum", None]},
        }, "required": ["concept", "entity", "entity_type", "period", "period_end", "aggregation"]})

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            if set(request.arguments) != {"concept", "entity", "entity_type", "period", "period_end", "aggregation"}:
                raise ValueError("invalid analytics_account_query fields")
            args = request.arguments
            result = AccountQueryExecutor(self.db_path, self.catalog).execute(AccountQuery(
                _required_string(args, "concept"), _required_string(args, "entity"), _required_string(args, "entity_type"),
                _required_string(args, "period"), _optional_string(args, "period_end"), _optional_string(args, "aggregation")))
            fact = {"metric_key": result.concept_id, "value": result.value, "unit": result.unit, "entity_id": result.entity_id, "period": result.period}
            coverage = {**result.coverage, "universe_kind": "account_mapping", "eligible_count": len(result.coverage["expected_periods"]), "observed_count": len(result.coverage["observed_periods"])}
            payload = {"evidence_id": request.call_id, "concept_id": result.concept_id, "entity": result.entity_id, "period": result.period, "value": result.value, "unit": result.unit, "basis": result.basis, "coverage": coverage, "mapped_account_rows": result.account_row_count, "source_mappings": result.source_mappings, "lineage": result.lineage}
            # A NONE result deliberately has no fact to bind.  Keeping an
            # empty governed dataset would make the synthesis guard render a
            # misleading entity-enumeration fallback instead of allowing the
            # model to state that evidence is unavailable (which is not zero).
            evidence = (ToolEvidence(request.call_id, "governed_dataset", {"tool_name": self.name, "source_kind": "account_concept"}, {"asset": result.entity_id}, {"metric_key": result.concept_id, "aggregation": args["aggregation"], "accounting_basis": result.basis, "entity_grain": result.entity_type, "period_grain": "month", "universe_kind": "account_mapping"}, result.lineage, coverage, (fact,)) if result.value is not None else None)
            return ToolResult(request.call_id, True, json.dumps(payload, ensure_ascii=False, default=str), {"tool_name": self.name, "arguments": args, "coverage": coverage, "accounting_basis": result.basis, "mapped_account_rows": result.account_row_count}, evidence=evidence)
        except (AccountQueryError, KeyError, TypeError, ValueError) as exc:
            payload = {"error_type": "semantic_query_error", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False), {"tool_name": self.name, "error": payload})


@dataclass
class ListAssetsAction:
    """Governed enumeration of the assets of a fund.

    Not a metric, so it deliberately does not go through the metric catalog;
    it reads `dim_fondo`/`dim_activo` directly. Coverage is *derived* from the
    same expected-universe semantics used everywhere else, never asserted.
    """

    db_path: Path
    name: str = "list_assets"
    description: str = (
        "Enumerates the canonical assets of a fund, optionally as of a given month, "
        "marking each one as currently applicable or historical (divested)."
    )

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, {
            "type": "object", "additionalProperties": False,
            "properties": {
                "fund": {"type": "string", "description": "Canonical fund key."},
                "period": {"type": ["string", "null"], "description": "Optional month in YYYY-MM format; use null for the assets applicable today."},
            },
            "required": ["fund", "period"],
        })

    def execute(self, request: ToolRequest) -> ToolResult:
        allowed = frozenset({"fund", "period"})
        try:
            unknown = sorted(set(request.arguments) - allowed)
            if unknown:
                raise ValueError(f"unknown {self.name} fields: {', '.join(unknown)}")
            fund = _required_string(request.arguments, "fund")
            period = _optional_string(request.arguments, "period")
            if not CanonicalScopeValidator(self.db_path).validate_fund(fund).valid:
                raise SemanticQueryError(f"unknown canonical fund: {fund}")
            rows = _fund_asset_rows(self.db_path, fund)
            # With a period, the applicable universe is the one
            # expected_asset_universe would derive; without one, "now" means
            # vigente_hasta IS NULL.
            eligible = (expected_asset_universe(self.db_path, fund, period).eligible_keys if period
                        else frozenset(key for key, vigente_hasta, _ in rows if vigente_hasta is None))
            facts = tuple({"entity_id": key, "name": nombre, "vigente_hasta": vigente_hasta,
                           "applicable": key in eligible, "period": period}
                          for key, vigente_hasta, nombre in rows)
            observed = frozenset(fact["entity_id"] for fact in facts if fact["applicable"])
            coverage = {"universe_kind": "fund_assets", "eligible_count": len(eligible),
                        "observed_count": len(observed), "eligible_ids": sorted(eligible),
                        "observed_ids": sorted(observed),
                        "status": "complete" if eligible and eligible <= observed else ("partial" if eligible else "unknown")}
            payload = {"evidence_id": request.call_id, "fund": fund, "period": period, "assets": list(facts),
                       "applicable_count": len(observed), "total_count": len(facts)}
            evidence = ToolEvidence(
                evidence_id=request.call_id, evidence_class="governed_dataset",
                source={"tool_name": self.name, "source_kind": "canonical"},
                scope={"fund": fund}, semantic_contract={"entity_grain": "asset", "universe_kind": "fund_assets"},
                provenance={"tables": ["dim_fondo", "dim_activo"]}, coverage=coverage, facts=facts,
            )
            trace = {"tool_name": self.name, "arguments": {"fund": fund, "period": period},
                     "result": {"row_count": len(facts), "coverage_status": coverage["status"],
                                "eligible_count": coverage["eligible_count"]}}
            return ToolResult(request.call_id, True, json.dumps(payload, ensure_ascii=False, default=str),
                              trace=trace, evidence=evidence)
        except SemanticQueryError as exc:
            payload = {"error_type": "semantic_query_error", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False),
                              trace={"tool_name": self.name, "error": {"error_type": "semantic_query_error", "message": str(exc)}})
        except (KeyError, TypeError, ValueError) as exc:
            payload = {"error_type": "invalid_request", "error": str(exc)}
            return ToolResult(request.call_id, False, json.dumps(payload, ensure_ascii=False),
                              trace={"tool_name": self.name, "error": {"error_type": "invalid_request", "message": str(exc)}})


def _fund_asset_rows(db_path: Path, fund_key: str) -> list[tuple]:
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT activo_key, vigente_hasta, nombre FROM dim_activo WHERE fondo_key=? ORDER BY activo_key",
            (fund_key,),
        ).fetchall()
    finally:
        conn.close()


def _period_range_coverage(rows: tuple) -> dict[str, object]:
    """Coverage for a time series. There is no asset universe to compare
    against, so completeness is expressed over the observed period range and
    `expected_asset_universe` is never consulted."""
    periods = sorted({r.period for r in rows})
    return {"universe_kind": "period_range", "eligible_count": len(periods),
            "observed_count": len(periods), "eligible_ids": periods, "observed_ids": periods,
            "entity_ids": sorted({r.entity_id for r in rows}),
            "period_start": periods[0] if periods else None,
            "period_end": periods[-1] if periods else None,
            "status": "complete"}


def _governed_dataset_coverage(db_path: Path, scope: dict[str, str], arguments: dict[str, object], rows: tuple) -> dict[str, object]:
    """Deterministic complete/partial/unknown coverage for one governed
    multi-row result. `unknown` whenever scope isn't a canonical fund key or
    the expected universe cannot be derived -- never inferred as complete
    from absence of a contrary signal."""
    fund_key = scope.get("fund")
    observed = frozenset(r.entity_id for r in rows)
    requested = arguments.get("assets")
    if isinstance(requested, list) and requested:
        # An explicit subset IS the expected universe -- membership and
        # temporal applicability were already validated before execution.
        eligible = frozenset(str(item) for item in requested)
        return {"universe_kind": "explicit_subset", "eligible_count": len(eligible),
                "observed_count": len(observed), "eligible_ids": sorted(eligible),
                "observed_ids": sorted(observed),
                "status": "complete" if eligible <= observed else "partial"}
    if not fund_key or not CanonicalScopeValidator(db_path).validate_fund(fund_key).valid:
        return {"universe_kind": "fund_assets", "eligible_count": None, "observed_count": len(observed),
                "eligible_ids": None, "observed_ids": sorted(observed), "status": "unknown"}
    period_ref = arguments.get("period_end") or arguments.get("period")
    universe = expected_asset_universe(db_path, fund_key, str(period_ref))
    if universe.status != "determined":
        return {"universe_kind": "fund_assets", "eligible_count": None, "observed_count": len(observed),
                "eligible_ids": None, "observed_ids": sorted(observed), "status": "unknown"}
    eligible = universe.eligible_keys
    status = "complete" if eligible and eligible <= observed else ("partial" if eligible else "unknown")
    return {"universe_kind": "fund_assets", "eligible_count": len(eligible), "observed_count": len(observed),
            "eligible_ids": sorted(eligible), "observed_ids": sorted(observed), "status": status}


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
