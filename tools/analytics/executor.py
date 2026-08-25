"""Offline executor for catalog-governed, read-only analytics requests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tools.analytics.catalog import load_metric_catalog
from tools.analytics.models import (
    Aggregation, DerivedKpiAccess, EntityReference, EntityType, FallbackAccess, RollupRatioViewAccess,
    SemanticQuery, ViewMetricAccess,
)
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox


class SemanticQueryError(ValueError):
    """A fail-closed semantic-contract rejection with safe explanation data."""

    def __init__(self, message: str, *, code: str = "semantic_query_error", metadata: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.metadata = metadata or {}


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

    def to_semantic_query(self) -> SemanticQuery:
        entities = tuple(
            [EntityReference(fund, EntityType.FUND) for fund in self.funds]
            + [EntityReference(asset, EntityType.ASSET) for asset in self.assets]
        )
        aggregation = Aggregation(self.aggregation) if self.aggregation else None
        return SemanticQuery(self.metric, entities, self.period, self.period_end, aggregation,
                             group_by=self.group_by, order_by=self.order_by, limit=self.limit)


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
    def __init__(self, db_path: Path, catalog_path: Path | None = None):
        self._sandbox = LiveReadOnlySandbox(db_path)
        self._catalog = load_metric_catalog(catalog_path)

    def execute(self, request: AnalyticsQueryRequest) -> AnalyticsResult:
        query = request.to_semantic_query()
        if query.metric_id not in self._catalog.metrics:
            raise SemanticQueryError(f"unknown metric: {query.metric_id}")
        metric = self._catalog.metrics[query.metric_id]
        if not query.period_start:
            raise SemanticQueryError("period is required")
        if query.temporal_aggregation not in (None, *metric.allowed_temporal_aggregations):
            raise SemanticQueryError(
                "aggregation is not permitted by metric contract",
                code="invalid_aggregation",
                metadata={
                    "metric_id": metric.key,
                    "metric_nature": metric.nature.value,
                    "requested_aggregation": query.temporal_aggregation.value,
                    "allowed_aggregations": [item.value for item in metric.allowed_temporal_aggregations],
                },
            )
        if request.group_by and request.group_by not in metric.allowed_dimensions:
            raise SemanticQueryError("grouping is not permitted by metric contract")
        if request.group_by and request.group_by != metric.entity_grain:
            raise SemanticQueryError("grouping must match metric entity grain")
        if request.order_by not in (None, "value_desc", "value_asc") or (request.limit is not None and request.limit < 1):
            raise SemanticQueryError("invalid order or limit")
        if isinstance(metric.access, FallbackAccess):
            records, entity_type = self._fallback_records(metric.access, request)
        else:
            sql, params, entity_type = self._access_sql(metric.access, request)
            with self._sandbox.connect() as connection:
                records = connection.execute(sql, params).fetchall()
        rows = tuple(AnalyticsRow(metric.key, record[0], entity_type, record[1], record[2], metric.unit,
                                  metric.source_kind, {"formula": record[3], "ingest_run_id": record[4]}) for record in records)
        if query.temporal_aggregation is not None:
            rows = self._aggregate(rows, query)
        return AnalyticsResult(self._catalog.version, "breakdown" if request.group_by else "scalar", rows)

    @staticmethod
    def _aggregate(rows: tuple[AnalyticsRow, ...], query: SemanticQuery) -> tuple[AnalyticsRow, ...]:
        expected = _month_range(query.period_start, query.period_end or query.period_start)
        by_entity: dict[tuple[str, str], list[AnalyticsRow]] = {}
        for row in rows:
            by_entity.setdefault((row.entity_id, row.entity_type), []).append(row)
        aggregated: list[AnalyticsRow] = []
        for (entity_id, entity_type), entity_rows in by_entity.items():
            observed = {row.period for row in entity_rows}
            if observed != set(expected):
                raise SemanticQueryError("coverage is incomplete for requested aggregation")
            if any(row.value is None for row in entity_rows):
                raise SemanticQueryError("coverage contains null values for requested aggregation")
            value = sum(float(row.value) for row in entity_rows)
            lineage = {
                "source_period_count": len(entity_rows), "source_periods": expected,
                "formula": sorted({str(row.provenance.get("formula")) for row in entity_rows}),
                "ingest_run_ids": sorted({row.provenance.get("ingest_run_id") for row in entity_rows if row.provenance.get("ingest_run_id") is not None}),
            }
            aggregated.append(AnalyticsRow(entity_id=entity_id, entity_type=entity_type,
                metric_key=entity_rows[0].metric_key, period=f"{expected[0]}..{expected[-1]}",
                value=value, unit=entity_rows[0].unit, source_kind=entity_rows[0].source_kind,
                provenance=lineage))
        return tuple(aggregated)


    def _access_sql(self, access, request: AnalyticsQueryRequest):
        if isinstance(access, DerivedKpiAccess):
            return self._derived_sql(access, request)
        if isinstance(access, ViewMetricAccess):
            return self._view_sql(access, request)
        raise SemanticQueryError("unsupported access strategy")

    def _fallback_records(self, access: FallbackAccess, request: AnalyticsQueryRequest):
        """Primary source wins for any (entity, period) it covers. The
        fallback is only consulted for cells the primary source is silent
        on — never merged or averaged with a primary value for the same
        cell, so precedence stays deterministic."""
        primary_sql, primary_params, entity_type = self._access_sql(access.primary, request)
        with self._sandbox.connect() as connection:
            primary_records = connection.execute(primary_sql, primary_params).fetchall()
        covered = {(record[0], record[1]) for record in primary_records}
        records = list(primary_records)
        if isinstance(access.fallback, RollupRatioViewAccess):
            for fund in request.funds or ():
                if fund not in access.fallback.views:
                    continue
                fb_sql, fb_params = self._rollup_sql(access.fallback, fund, request)
                with self._sandbox.connect() as connection:
                    fb_records = connection.execute(fb_sql, fb_params).fetchall()
                for record in fb_records:
                    key = (record[0], record[1])
                    if key not in covered:
                        records.append(record)
                        covered.add(key)
        records.sort(key=lambda record: (record[1], record[0]))
        return records, entity_type

    def _rollup_sql(self, access: RollupRatioViewAccess, fund: str, request: AnalyticsQueryRequest):
        view = access.views[fund]
        exclude_clause = ""
        params: list[object] = []
        if access.exclude_column:
            exclude_clause = f" AND ({access.exclude_column} IS NULL OR {access.exclude_column} != ?)"
            params.append(access.exclude_value)
        formula = f"rollup_ratio:{view}:sum({access.numerator_column})/sum({access.denominator_column})"
        # Only sum rows where both sides of the ratio are present for the same
        # observation — a numerator-only or denominator-only row is not a valid
        # component pair and would silently skew the ratio of sums.
        pair_clause = f"{access.numerator_column} IS NOT NULL AND {access.denominator_column} IS NOT NULL"
        source = view
        if access.dedupe_columns and access.precedence_column and access.precedence_order:
            partition = ", ".join(["periodo", *access.dedupe_columns])
            precedence_case = " ".join(
                f"WHEN {access.precedence_column}=? THEN {rank}" for rank, _ in enumerate(access.precedence_order)
            )
            source = (
                f"(SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition} "
                f"ORDER BY (CASE {precedence_case} ELSE 999 END)) AS rn FROM {view})"
            )
            precedence_params = list(access.precedence_order)
        else:
            precedence_params = []
        rn_filter = " AND rn = 1" if precedence_params else ""
        sql = (
            f"SELECT ? AS entidad_key, periodo, "
            f"SUM({access.numerator_column}) * 100.0 / SUM({access.denominator_column}) AS valor, "
            f"'{formula}' AS formula, NULL AS ingest_run_id "
            f"FROM {source} WHERE periodo BETWEEN ? AND ?{exclude_clause} AND {pair_clause}{rn_filter} "
            f"GROUP BY periodo HAVING SUM({access.denominator_column}) > 0 ORDER BY periodo"
        )
        params = [fund, *precedence_params, request.period, request.period_end or request.period, *params]
        return sql, tuple(params)

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


def _month_range(start: str, end: str) -> list[str]:
    try:
        start_year, start_month = map(int, start.split("-"))
        end_year, end_month = map(int, end.split("-"))
    except ValueError as exc:
        raise SemanticQueryError("period must use YYYY-MM") from exc
    if not (1 <= start_month <= 12 and 1 <= end_month <= 12) or (end_year, end_month) < (start_year, start_month):
        raise SemanticQueryError("invalid period range")
    months = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months
