"""Offline executor for catalog-governed, read-only analytics requests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tools.analytics.catalog import load_metric_catalog
from tools.analytics.models import DerivedKpiAccess, ViewMetricAccess
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox


class SemanticQueryError(ValueError):
    pass


@dataclass(frozen=True)
class AnalyticsQueryRequest:
    metric: str
    funds: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()
    period: str = ""
    period_end: str | None = None
    group_by: str | None = None
    order_by: Literal["value_desc", "value_asc"] | None = None
    limit: int | None = None
    aggregation: str | None = None


@dataclass(frozen=True)
class AnalyticsRow:
    metric_key: str
    entity_id: str
    entity_type: str
    period: str
    value: float | None
    unit: str
    source_kind: str
    provenance: dict[str, object]


@dataclass(frozen=True)
class AnalyticsResult:
    catalog_version: int
    result_kind: str
    rows: tuple[AnalyticsRow, ...]


class AnalyticsExecutor:
    def __init__(self, db_path: Path):
        self._sandbox = LiveReadOnlySandbox(db_path)
        self._catalog = load_metric_catalog()

    def execute(self, request: AnalyticsQueryRequest) -> AnalyticsResult:
        if request.metric not in self._catalog.metrics:
            raise SemanticQueryError(f"unknown metric: {request.metric}")
        metric = self._catalog.metrics[request.metric]
        if not request.period or request.aggregation is not None:
            raise SemanticQueryError("period is required and aggregation is not supported")
        if request.group_by and request.group_by not in metric.allowed_dimensions:
            raise SemanticQueryError("grouping is not permitted by metric contract")
        if request.group_by and request.group_by != metric.entity_grain:
            raise SemanticQueryError("grouping must match metric entity grain")
        if request.order_by not in (None, "value_desc", "value_asc") or (request.limit is not None and request.limit < 1):
            raise SemanticQueryError("invalid order or limit")
        if isinstance(metric.access, DerivedKpiAccess):
            sql, params, entity_type = self._derived_sql(metric.access, request)
        elif isinstance(metric.access, ViewMetricAccess):
            sql, params, entity_type = self._view_sql(metric.access, request)
        else:
            raise SemanticQueryError("unsupported access strategy")
        with self._sandbox.connect() as connection:
            records = connection.execute(sql, params).fetchall()
        rows = tuple(AnalyticsRow(metric.key, record[0], entity_type, record[1], record[2], metric.unit,
                                  metric.source_kind, {"formula": record[3], "ingest_run_id": record[4]}) for record in records)
        return AnalyticsResult(self._catalog.version, "breakdown" if request.group_by else "scalar", rows)

    def _derived_sql(self, access: DerivedKpiAccess, request: AnalyticsQueryRequest):
        if access.entity_type != "fondo":
            return self._derived_asset_sql(access, request)
        if request.assets or request.group_by:
            raise SemanticQueryError("metric does not support asset scope or grouping")
        funds = request.funds or ()
        if not funds:
            raise SemanticQueryError("fund scope is required")
        placeholders = ",".join("?" for _ in funds)
        sql = ("SELECT entidad_key, periodo, valor, formula, ingest_run_id FROM derived_kpi "
               f"WHERE entidad_tipo=? AND kpi=? AND periodo BETWEEN ? AND ? AND entidad_key IN ({placeholders}) "
               "ORDER BY periodo, entidad_key")
        return sql, (access.entity_type, access.kpi, request.period, request.period_end or request.period, *funds), "fund"

    def _derived_asset_sql(self, access: DerivedKpiAccess, request: AnalyticsQueryRequest):
        """Asset-grain derived_kpi access: explicit-asset lookup, or a
        fund-scoped breakdown joined to dim_activo (same join shape as
        `_view_sql`) with an optional explicit asset subset."""
        if request.funds and len(request.funds) > 1:
            raise SemanticQueryError("asset-grain metrics accept at most one fund scope")
        period_end = request.period_end or request.period
        params: list[object] = [access.entity_type, access.kpi, request.period, period_end]
        filters = ["k.entidad_tipo=?", "k.kpi=?", "k.periodo BETWEEN ? AND ?"]
        join = ""
        if request.funds:
            join = " JOIN dim_activo a ON a.activo_key=k.entidad_key"
            filters.append("a.fondo_key=?")
            params.append(request.funds[0])
        elif not request.assets:
            raise SemanticQueryError("asset or fund scope is required")
        if request.assets:
            filters.append("k.entidad_key IN (" + ",".join("?" for _ in request.assets) + ")")
            params.extend(request.assets)
        if request.order_by:
            order = "DESC" if request.order_by == "value_desc" else "ASC"
            order_clause = f"k.valor {order}, k.entidad_key"
        else:
            order_clause = "k.periodo, k.entidad_key"
        limit = f" LIMIT {int(request.limit)}" if request.limit else ""
        sql = ("SELECT k.entidad_key, k.periodo, k.valor, k.formula, k.ingest_run_id "
               f"FROM derived_kpi k{join} WHERE {' AND '.join(filters)} ORDER BY {order_clause}{limit}")
        return sql, tuple(params), "asset"

    def _view_sql(self, access: ViewMetricAccess, request: AnalyticsQueryRequest):
        filters, params = ["v.periodo BETWEEN ? AND ?"], [request.period, request.period_end or request.period]
        if request.funds:
            filters.append("a.fondo_key IN (" + ",".join("?" for _ in request.funds) + ")")
            params.extend(request.funds)
        if request.assets:
            filters.append("v.activo_key IN (" + ",".join("?" for _ in request.assets) + ")")
            params.extend(request.assets)
        order = "DESC" if request.order_by == "value_desc" else "ASC"
        limit = f" LIMIT {request.limit}" if request.limit else ""
        sql = (f"SELECT v.activo_key, v.periodo, v.{access.value_column}, v.fuente, NULL "
               f"FROM {access.view} v JOIN dim_activo a ON a.activo_key=v.activo_key "
               f"WHERE {' AND '.join(filters)} ORDER BY v.{access.value_column} {order}, v.activo_key{limit}")
        return sql, tuple(params), "asset"
