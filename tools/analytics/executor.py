"""Offline executor for catalog-governed, read-only analytics requests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tools.analytics.catalog import load_metric_catalog
from tools.analytics.models import (
    Aggregation, DerivedKpiAccess, DerivedKpiVariantSource, DimensionedAccess, EntityReference, EntityType,
    FallbackAccess, MetricDefinition, RollupRatioViewAccess, SegmentedVacancyAccess,
    SemanticQuery, TableVariantSource, ViewMetricAccess,
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
    space_types: tuple[str, ...] = ()
    dimensions: tuple[tuple[str, str], ...] = ()
    selector: str | None = None

    def to_semantic_query(self) -> SemanticQuery:
        entities = tuple(
            [EntityReference(fund, EntityType.FUND) for fund in self.funds]
            + [EntityReference(asset, EntityType.ASSET) for asset in self.assets]
        )
        aggregation = Aggregation(self.aggregation) if self.aggregation else None
        return SemanticQuery(self.metric, entities, self.period, self.period_end, aggregation,
                             group_by=self.group_by, order_by=self.order_by, limit=self.limit,
                             space_types=self.space_types,
                             dimensions=tuple(sorted(self.dimensions)), selector=self.selector)


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
    dimensions: dict[str, object] = None


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
        if isinstance(metric.access, DimensionedAccess):
            rows = tuple(self._dimensioned_rows(metric, request, query))
            if query.temporal_aggregation is not None:
                rows = self._aggregate(rows, query, metric)
            kind = "scalar" if len({(row.entity_id, row.entity_type) for row in rows}) <= 1 else "breakdown"
            return AnalyticsResult(self._catalog.version, kind, rows)
        if isinstance(metric.access, SegmentedVacancyAccess):
            rows = self._segmented_rows(metric, request)
            return AnalyticsResult(self._catalog.version, "scalar", tuple(rows))
        if isinstance(metric.access, FallbackAccess):
            records, entity_type = self._fallback_records(metric.access, request)
        else:
            sql, params, entity_type = self._access_sql(metric.access, request)
            with self._sandbox.connect() as connection:
                records = connection.execute(sql, params).fetchall()
        rows = tuple(AnalyticsRow(metric.key, record[0], entity_type, record[1], record[2], metric.unit,
                                  metric.source_kind, {"formula": record[3], "ingest_run_id": record[4]}, {}) for record in records)
        if query.temporal_aggregation is not None:
            rows = self._aggregate(rows, query)
        return AnalyticsResult(self._catalog.version, "breakdown" if request.group_by else "scalar", rows)

    @staticmethod
    def _aggregate(rows: tuple[AnalyticsRow, ...], query: SemanticQuery,
                   metric: MetricDefinition | None = None) -> tuple[AnalyticsRow, ...]:
        expected = _month_range(query.period_start, query.period_end or query.period_start)
        # An EVENT metric is observed only when the event happened: a month
        # without a distribution is not a coverage gap and must not block the
        # aggregation the way a missing month of a dense monthly series does.
        # It still never turns absence into a zero -- with no events at all
        # there are no rows here and nothing is aggregated or reported.
        event_stream = metric is not None and metric.temporal_completeness == "event"
        by_entity: dict[tuple[str, str], list[AnalyticsRow]] = {}
        for row in rows:
            by_entity.setdefault((row.entity_id, row.entity_type), []).append(row)
        aggregated: list[AnalyticsRow] = []
        for (entity_id, entity_type), entity_rows in by_entity.items():
            observed = {row.period for row in entity_rows}
            if event_stream:
                if not observed <= set(expected):
                    raise SemanticQueryError("aggregation covers periods outside the requested range")
            elif observed != set(expected):
                raise SemanticQueryError("coverage is incomplete for requested aggregation")
            if any(row.value is None for row in entity_rows):
                raise SemanticQueryError("coverage contains null values for requested aggregation")
            value = sum(float(row.value) for row in entity_rows)
            lineage = {
                "source_period_count": len(entity_rows),
                "source_periods": sorted(observed) if event_stream else expected,
                "temporal_completeness": "event" if event_stream else "dense",
                "formula": sorted({str(row.provenance.get("formula")) for row in entity_rows}),
                "ingest_run_ids": sorted({row.provenance.get("ingest_run_id") for row in entity_rows if row.provenance.get("ingest_run_id") is not None}),
            }
            aggregated.append(AnalyticsRow(entity_id=entity_id, entity_type=entity_type,
                metric_key=entity_rows[0].metric_key, period=f"{expected[0]}..{expected[-1]}",
                value=value, unit=entity_rows[0].unit, source_kind=entity_rows[0].source_kind,
                provenance=lineage,
                # An aggregated row keeps the semantic dimensions of its
                # operands (they are identical by construction: one variant
                # was selected for the whole request), so a summed fact is
                # still self-describing -- "distribuciones tipo dividendo",
                # not an unlabelled number.
                dimensions=dict(entity_rows[0].dimensions or {})))
        return tuple(aggregated)


    def _access_sql(self, access, request: AnalyticsQueryRequest):
        if isinstance(access, DerivedKpiAccess):
            return self._derived_sql(access, request)
        if isinstance(access, ViewMetricAccess):
            return self._view_sql(access, request)
        raise SemanticQueryError("unsupported access strategy")

    @staticmethod
    def _validate_units(units: dict[str, str]) -> str:
        values = set(units.values())
        if len(values) != 1:
            raise SemanticQueryError("incompatible physical units cannot be aggregated", code="incompatible_units")
        return next(iter(values))

    def _segmented_rows(self, metric, request: AnalyticsQueryRequest) -> list[AnalyticsRow]:
        access: SegmentedVacancyAccess = metric.access
        requested = request.space_types or tuple(access.source_labels)
        if not requested or len(set(requested)) != len(requested) or any(item not in access.source_labels for item in requested):
            raise SemanticQueryError("unknown or duplicate space type")
        unit = self._validate_units({item: access.measurement_units[item] for item in requested})
        if metric.entity_grain == "fund":
            if len(request.funds) != 1 or request.assets:
                raise SemanticQueryError("fund scope is required")
            candidates = access.asset_groups.get(request.funds[0], ())
            entity, entity_type = request.funds[0], "fund"
        else:
            if len(request.assets) != 1 or request.funds:
                raise SemanticQueryError("asset scope is required")
            candidates = (request.assets,)
            entity, entity_type = request.assets[0], "asset"
        labels = tuple(label for kind in requested for label in access.source_labels[kind])
        for group in candidates:
            placeholders, label_marks = ",".join("?" for _ in group), ",".join("?" for _ in labels)
            sql = (f"SELECT SUM(m2_vacantes), SUM(m2_gla), COUNT(*) FROM {access.view} "
                   f"WHERE {access.entity_column} IN ({placeholders}) AND periodo=? AND tipo_unidad IN ({label_marks}) "
                   "AND m2_vacantes IS NOT NULL AND m2_gla IS NOT NULL")
            with self._sandbox.connect() as connection:
                numerator, denominator, count = connection.execute(sql, (*group, request.period, *labels)).fetchone()
            if count:
                value = float(numerator) / float(denominator) if denominator else None
                return [AnalyticsRow(metric.key, entity, entity_type, request.period, value, metric.unit, metric.source_kind,
                    {"formula": "sum(m2_vacantes)/sum(m2_gla)", "numerator": numerator, "denominator": denominator,
                     "source_rows": count, "source_group": list(group)},
                    {"space_types": tuple(requested), "space_type": requested[0] if len(requested) == 1 else "combined",
                     "measurement_unit": unit, "coverage": "complete"})]
        return [AnalyticsRow(metric.key, entity, entity_type, request.period, None, metric.unit, metric.source_kind,
            {"formula": "sum(m2_vacantes)/sum(m2_gla)", "numerator": None, "denominator": None, "source_rows": 0},
            {"space_types": tuple(requested), "space_type": requested[0] if len(requested) == 1 else "combined",
             "measurement_unit": unit, "coverage": "none"})]

    # ------------------------------------------------------------------
    # Dimensioned access (fund financial surface)
    # ------------------------------------------------------------------

    def _dimensioned_rows(self, metric: MetricDefinition, request: AnalyticsQueryRequest,
                          query: SemanticQuery) -> list[AnalyticsRow]:
        access: DimensionedAccess = metric.access
        if len(request.funds) != 1 or request.assets:
            raise SemanticQueryError("fund scope is required")
        fund = request.funds[0]
        selected = self._resolve_dimensions(access, query)
        variant = access.select(selected)
        if variant is None:
            raise SemanticQueryError(
                "the requested combination of dimensions is not available for this metric",
                code="unavailable_dimension_combination",
                metadata={"metric_id": metric.key, "requested_dimensions": selected,
                          "available_combinations": [dict(item.values) for item in access.variants]},
            )
        entities = self._scope_entities(access, fund, request.selector)
        if not entities:
            raise SemanticQueryError(
                "no canonical sub-entity matches that selection",
                code="unknown_selector",
                metadata={"metric_id": metric.key, "fund": fund, "selector": request.selector},
            )
        period_end = request.period_end or request.period
        horizon = self._observed_horizon(access, fund)
        if horizon is not None and period_end > horizon:
            # The source is a payment SCHEDULE that runs decades past the last
            # real close (CONSOLIDADO_TRI reaches 2072). Reporting those rows
            # would present placeholder future entries -- many of them zero --
            # as observed amortization. The requested window is clamped to the
            # governed observed horizon instead; a window entirely beyond it
            # simply yields no observation, which is coverage NONE, not zero.
            period_end = horizon
            if period_end < request.period:
                return []
        rows: list[AnalyticsRow] = []
        for entity in entities:
            rows.extend(self._variant_rows(metric, variant, entity, request.period, period_end,
                                           selected, fund, horizon))
        rows.sort(key=lambda row: (row.period, row.entity_id))
        if request.order_by:
            rows.sort(key=lambda row: (row.value is None, row.value or 0.0),
                      reverse=request.order_by == "value_desc")
        if request.limit:
            rows = rows[: int(request.limit)]
        return rows

    @staticmethod
    def _resolve_dimensions(access: DimensionedAccess, query: SemanticQuery) -> dict[str, str]:
        """Apply catalog defaults, reject unknown values, and fail closed --
        with the allowed values attached -- on a dimension the caller left
        open and the catalog gives no default for."""
        supplied = dict(query.dimensions)
        unknown = sorted(set(supplied) - {dimension.name for dimension in access.dimensions})
        if unknown:
            raise SemanticQueryError(
                f"dimension is not part of this metric contract: {', '.join(unknown)}",
                code="unknown_dimension",
                metadata={"metric_id": query.metric_id, "unknown_dimensions": unknown,
                          "declared_dimensions": [dimension.name for dimension in access.dimensions]},
            )
        selected: dict[str, str] = {}
        missing: list[dict[str, object]] = []
        for dimension in access.dimensions:
            value = supplied.get(dimension.name, dimension.default)
            if value is None:
                missing.append({"dimension": dimension.name, "allowed_values": list(dimension.values)})
                continue
            if value not in dimension.values:
                raise SemanticQueryError(
                    f"unknown value for dimension {dimension.name}: {value}",
                    code="unknown_dimension_value",
                    metadata={"metric_id": query.metric_id, "dimension": dimension.name,
                              "requested_value": value, "allowed_values": list(dimension.values)},
                )
            selected[dimension.name] = value
        if missing:
            raise SemanticQueryError(
                "the metric is not identified until every semantic dimension is chosen",
                code="dimension_required",
                metadata={"metric_id": query.metric_id, "missing_dimensions": missing},
            )
        return selected

    def _scope_entities(self, access: DimensionedAccess, fund: str, selector: str | None) -> list[dict[str, str]]:
        """Resolve the sub-entities of a fund for this metric's scope.

        Returns dicts with the source key (what the SQL filters on) and the
        reported canonical identity (what a claim binds to). They differ only
        for ``fund_template``, where a synthetic consolidated key is read but
        the fact belongs to the fund itself.
        """
        if access.scope == "fund_template":
            assert access.entity_key_template is not None
            if selector is not None:
                raise SemanticQueryError("this metric has no sub-entity selector", code="unknown_selector")
            return [{"source_key": access.entity_key_template.format(fund=fund),
                     "entity_id": fund, "entity_type": "fund", "label": fund}]
        if access.scope == "series":
            sql = "SELECT nemotecnico, serie FROM dim_serie WHERE fondo_key=? ORDER BY serie, nemotecnico"
            with self._sandbox.connect() as connection:
                records = connection.execute(sql, (fund,)).fetchall()
            candidates = [{"source_key": key, "entity_id": key, "entity_type": "series", "label": str(serie)}
                          for key, serie in records]
        else:
            sql = "SELECT credito_key FROM dim_credito WHERE fondo_key=? ORDER BY credito_key"
            with self._sandbox.connect() as connection:
                records = connection.execute(sql, (fund,)).fetchall()
            candidates = [{"source_key": key, "entity_id": key, "entity_type": "credit", "label": str(key)}
                          for (key,) in records]
        if selector is None:
            return candidates
        wanted = selector.strip().casefold()
        return [item for item in candidates
                if item["label"].casefold() == wanted or item["entity_id"].casefold() == wanted]

    def _observed_horizon(self, access: DimensionedAccess, fund: str) -> str | None:
        """Latest period for which the fund has a real observed financial
        close, read from a governed backward-looking KPI series declared in
        the catalog. It is what separates an amortization that ALREADY
        happened from one that is merely scheduled -- without it,
        MAX(periodo) on a payment schedule would report a placeholder row
        decades in the future as the latest real amortization."""
        source = access.observed_horizon
        if source is None:
            return None
        with self._sandbox.connect() as connection:
            row = connection.execute(
                "SELECT MAX(periodo) FROM derived_kpi WHERE entidad_tipo=? AND kpi=? AND entidad_key=?",
                (source.entity_type, source.kpi, fund)).fetchone()
        return str(row[0]) if row and row[0] else None

    def _variant_rows(self, metric: MetricDefinition, variant, entity: dict[str, str], period: str,
                      period_end: str, selected: dict[str, str], fund: str,
                      horizon: str | None) -> list[AnalyticsRow]:
        source = variant.source
        base_dimensions = {**selected, "fund": fund}
        if entity["entity_type"] == "series":
            base_dimensions["series"] = entity["label"]
        elif entity["entity_type"] == "credit":
            base_dimensions["credit"] = entity["entity_id"]
        if isinstance(source, DerivedKpiVariantSource):
            return self._persisted_kpi_rows(metric, source, entity, period, period_end, base_dimensions)
        return self._table_rows(metric, source, entity, period, period_end, base_dimensions, horizon)

    def _persisted_kpi_rows(self, metric: MetricDefinition, source: DerivedKpiVariantSource,
                            entity: dict[str, str], period: str, period_end: str,
                            dimensions: dict[str, object]) -> list[AnalyticsRow]:
        variant_clause = "variante IS NULL" if source.variante is None else "variante=?"
        params: list[object] = [source.entity_type, source.kpi, entity["source_key"], period, period_end]
        if source.variante is not None:
            params.append(source.variante)
        sql = ("SELECT periodo, valor, formula, ingest_run_id, unidad FROM derived_kpi "
               "WHERE entidad_tipo=? AND kpi=? AND entidad_key=? AND periodo BETWEEN ? AND ? "
               f"AND {variant_clause} ORDER BY periodo")
        with self._sandbox.connect() as connection:
            records = connection.execute(sql, tuple(params)).fetchall()
        return [AnalyticsRow(metric.key, entity["entity_id"], entity["entity_type"], str(record[0]),
                             None if record[1] is None else float(record[1]), metric.unit, metric.source_kind,
                             {"formula": record[2], "ingest_run_id": record[3],
                              "source": "derived_kpi", "kpi": source.kpi, "variante": source.variante,
                              "source_entity_key": entity["source_key"], "source_unit": record[4],
                              "authority": "persisted_canonical_kpi"},
                             dict(dimensions))
                for record in records]

    def _table_rows(self, metric: MetricDefinition, source: TableVariantSource, entity: dict[str, str],
                    period: str, period_end: str, dimensions: dict[str, object],
                    horizon: str | None) -> list[AnalyticsRow]:
        filters = [f"{source.entity_column}=?"]
        params: list[object] = [entity["source_key"]]
        for column, value in source.filters:
            if value is None:
                filters.append(f"{column} IS NULL")
            else:
                filters.append(f"{column}=?")
                params.append(value)
        # A NULL measurement is missing data, never a zero: excluded at the
        # source so it can never be summed or reported as an observation.
        filters.append(f"{source.value_column} IS NOT NULL")
        period_expression = source.period_column or f"substr({source.date_column},1,7)"
        if source.temporal == "as_of":
            filters.append(f"{period_expression}<=?")
            params.append(period_end)
        else:
            filters.append(f"{period_expression} BETWEEN ? AND ?")
            params.extend([period, period_end])
        columns = [period_expression, source.value_column]
        extra = list(dict.fromkeys(
            [column for column in (source.date_column,) if column]
            + list(source.provenance_columns)
            + ([source.conversion.reference_column] if source.conversion else [])
        ))
        # Newest-first, with the measured value as the last tiebreak so the
        # ordering is total and reproducible even for a view (no rowid) and
        # even when a source holds two byte-identical snapshot rows.
        order = (f"{period_expression} DESC, "
                 + (f"{source.date_column} DESC, " if source.date_column else "")
                 + f"{source.value_column} DESC")
        sql = (f"SELECT {', '.join(columns + extra)} FROM {source.table} "
               f"WHERE {' AND '.join(filters)} ORDER BY {order}")
        with self._sandbox.connect() as connection:
            records = connection.execute(sql, tuple(params)).fetchall()
        return self._rows_from_records(metric, source, entity, records, extra, dimensions, horizon)

    def _rows_from_records(self, metric: MetricDefinition, source: TableVariantSource, entity: dict[str, str],
                           records: list, extra: list[str], dimensions: dict[str, object],
                           horizon: str | None) -> list[AnalyticsRow]:
        """Apply the declared temporal contract to already-ordered records.

        Records arrive newest-first, so "the first record for a key wins" is
        the single deterministic de-duplication rule used by every contract
        here -- which is exactly what stops the duplicated legacy distribution
        rows from being counted twice.
        """
        selected: list[tuple[str, object, dict[str, object]]] = []
        seen: set[tuple] = set()
        for record in records:
            period_value, value = str(record[0]), record[1]
            details = dict(zip(extra, record[2:]))
            if source.temporal == "event":
                key = (period_value, str(details.get(source.date_column))) + tuple(
                    str(details.get(column)) for column in source.dedupe_columns)
            else:
                key = (period_value,)
            if key in seen:
                continue
            seen.add(key)
            selected.append((period_value, value, details))
            if source.temporal == "as_of":
                break
        rows: list[AnalyticsRow] = []
        for period_value, value, details in selected:
            provenance: dict[str, object] = {
                "formula": f"{source.table}.{source.value_column}", "ingest_run_id": None,
                "source": source.table, "temporal_contract": source.temporal,
                "source_entity_key": entity["source_key"], "authority": "raw_governed_source",
                **{column: details[column] for column in extra if column in details},
            }
            row_dimensions = dict(dimensions)
            if horizon is not None:
                row_dimensions["schedule_basis"] = "observed" if period_value <= horizon else "scheduled"
                provenance["observed_horizon"] = horizon
            fact_extras: dict[str, object] = {}
            if source.conversion is not None:
                reference = details.get(source.conversion.reference_column)
                if isinstance(reference, (int, float)) and reference > 0:
                    fact_extras["presentation_conversion"] = {
                        "from_unit": source.conversion.from_unit, "to_unit": source.conversion.to_unit,
                        "temporal_basis": source.conversion.temporal_basis, "reference_value": float(reference),
                        "source": f"{source.table}.{source.conversion.reference_column}",
                        "reference_date": str(details.get(source.date_column) or period_value),
                    }
            rows.append(AnalyticsRow(metric.key, entity["entity_id"], entity["entity_type"], period_value,
                                     None if value is None else float(value), metric.unit, metric.source_kind,
                                     provenance, {**row_dimensions, **fact_extras}))
        rows.sort(key=lambda row: row.period)
        return rows

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
                groups = access.fallback.asset_groups.get(fund)
                if not groups:
                    continue
                for group in groups:
                    sql, params = self._rollup_sql(access.fallback, fund, group, request)
                    with self._sandbox.connect() as connection:
                        fb_records = connection.execute(sql, params).fetchall()
                    for record in fb_records:
                        key = (record[0], record[1])
                        if key not in covered:
                            records.append(record)
                            covered.add(key)
        records.sort(key=lambda record: (record[1], record[0]))
        return records, entity_type

    def _rollup_sql(self, access: RollupRatioViewAccess, fund: str, group: tuple[str, ...], request: AnalyticsQueryRequest):
        exclude_clause = ""
        exclude_params: list[object] = []
        if access.exclude_column:
            exclude_clause = f" AND ({access.exclude_column} IS NULL OR {access.exclude_column} != ?)"
            exclude_params.append(access.exclude_value)
        components = ",".join(sorted(group))
        formula = (
            f"rollup_ratio:{access.view}:[{components}]:"
            f"sum({access.numerator_column})/sum({access.denominator_column})"
        )
        # Only sum rows where both sides of the ratio are present for the same
        # observation — a numerator-only or denominator-only row is not a valid
        # component pair and would silently skew the ratio of sums.
        pair_clause = f"{access.numerator_column} IS NOT NULL AND {access.denominator_column} IS NOT NULL"
        entity_placeholders = ",".join("?" for _ in group)
        sql = (
            f"SELECT ? AS entidad_key, periodo, "
            f"SUM({access.numerator_column}) * 100.0 / SUM({access.denominator_column}) AS valor, "
            f"'{formula}' AS formula, NULL AS ingest_run_id "
            f"FROM {access.view} WHERE {access.entity_column} IN ({entity_placeholders}) "
            f"AND periodo BETWEEN ? AND ?{exclude_clause} AND {pair_clause} "
            f"GROUP BY periodo HAVING SUM({access.denominator_column}) > 0 ORDER BY periodo"
        )
        params = [fund, *group, request.period, request.period_end or request.period, *exclude_params]
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
