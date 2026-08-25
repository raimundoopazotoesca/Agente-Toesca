"""Deterministic executor for declarative governed dataset queries."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.datasets.catalog import load_dataset_catalog


class DatasetQueryError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetFilter:
    field: str
    op: str
    value: object
    value_end: object | None = None


@dataclass(frozen=True)
class DatasetMeasure:
    measure: str
    aggregation: str


@dataclass(frozen=True)
class GovernedDatasetQuery:
    dataset: str
    filters: tuple[DatasetFilter, ...]
    group_by: tuple[str, ...]
    measures: tuple[DatasetMeasure, ...]
    order_by: str | None = None
    descending: bool = True
    limit: int | None = None
    share_of_total: bool = False
    row_axis: str | None = None
    column_axis: str | None = None


@dataclass(frozen=True)
class DatasetQueryResult:
    rows: tuple[dict[str, object], ...]
    coverage: dict[str, object]
    contract: dict[str, object]


class GovernedDatasetExecutor:
    def __init__(self, db_path: Path, catalog_path: Path | None = None):
        self._sandbox = LiveReadOnlySandbox(db_path)
        self._catalog = load_dataset_catalog(catalog_path)

    def execute(self, query: GovernedDatasetQuery) -> DatasetQueryResult:
        definition = self._catalog.datasets.get(query.dataset)
        if definition is None:
            raise DatasetQueryError("unknown dataset")
        if not query.measures or len({m.measure for m in query.measures}) != len(query.measures):
            raise DatasetQueryError("one or more unique measures are required")
        visible_fields = set(definition.fields)
        axes = tuple(field for field in (query.row_axis, query.column_axis) if field is not None)
        if query.group_by and axes:
            raise DatasetQueryError("use group_by or row/column axes, not both")
        grouping = axes or query.group_by
        if any(field not in definition.dimensions and field not in visible_fields for field in grouping):
            raise DatasetQueryError("group_by field is not declared by dataset")
        if len(grouping) > 4:
            raise DatasetQueryError("at most four visible dimensions are supported")
        if query.column_axis and not query.row_axis:
            raise DatasetQueryError("column_axis requires row_axis")
        used_fields = set(grouping) | {item.field for item in query.filters}
        for field, supported_assets in definition.dimension_coverage.items():
            if field not in used_fields:
                continue
            asset_filters = [item for item in query.filters if item.field == "activo_key" and item.op in {"eq", "in"}]
            requested_assets = {str(asset_filters[0].value)} if asset_filters and asset_filters[0].op == "eq" else (
                {str(value) for value in asset_filters[0].value} if asset_filters else set())
            unsupported = requested_assets - set(supported_assets)
            if unsupported:
                raise DatasetQueryError(f"{field} is unsupported for asset: {', '.join(sorted(unsupported))}")
        where, params = ["is_current=1"], []
        for field in set(grouping) | {item.field for item in query.filters}:
            if field in definition.dimension_coverage:
                where.append(f'"{field}" IS NOT NULL')
        operators = {"eq": "=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        for item in query.filters:
            if item.field not in visible_fields:
                raise DatasetQueryError("filter field is not declared by dataset")
            if item.op in operators:
                where.append(f'"{item.field}" {operators[item.op]} ?'); params.append(item.value)
            elif item.op == "in" and isinstance(item.value, (list, tuple)) and item.value:
                where.append(f'"{item.field}" IN ({",".join("?" for _ in item.value)})'); params.extend(item.value)
            elif item.op == "between" and item.value_end is not None:
                where.append(f'"{item.field}" BETWEEN ? AND ?'); params.extend((item.value, item.value_end))
            else:
                raise DatasetQueryError("invalid governed filter")
        expressions = []
        for item in query.measures:
            spec = definition.measures.get(item.measure)
            if not spec or item.aggregation not in spec["allowed_aggregations"]:
                raise DatasetQueryError("aggregation is not permitted by measure contract")
            field = str(spec["field"])
            if "sql_expression" in spec:
                expr = str(spec["sql_expression"])
            else:
                aggregate = {"sum": "SUM", "count": "COUNT", "distinct_count": "COUNT(DISTINCT", "avg": "AVG"}[item.aggregation]
                expr = f'{aggregate}("{field}")' if item.aggregation != "distinct_count" else f'COUNT(DISTINCT "{field}")'
            expressions.append(f'{expr} AS "{item.measure}"')
        select_dimensions = [f'"{field}"' for field in grouping]
        source = f'({definition.source_sql})' if definition.source_sql else f'"{definition.object_name}"'
        sql = f'SELECT {", ".join(select_dimensions + expressions)} FROM {source} WHERE {" AND ".join(where)}'
        if grouping: sql += " GROUP BY " + ", ".join(select_dimensions)
        if query.order_by:
            if query.order_by not in {m.measure for m in query.measures}: raise DatasetQueryError("order_by must name a selected measure")
            sql += f' ORDER BY "{query.order_by}" {"DESC" if query.descending else "ASC"}'
        with self._sandbox.connect() as conn:
            conn.create_function("governed_jll_floor", 1, _jll_floor)
            eligible_count = conn.execute(f'SELECT COUNT(*) FROM {source} WHERE {" AND ".join(where)}', params).fetchone()[0]
            cursor = conn.execute(sql, params)
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        full_count = len(rows)
        if query.share_of_total:
            if len(query.measures) != 1 or query.measures[0].aggregation not in {"sum", "count", "distinct_count"}:
                raise DatasetQueryError("share_of_total requires one additive/count measure")
            total = sum(float(row[query.measures[0].measure] or 0) for row in rows)
            for row in rows: row["share_of_total"] = (float(row[query.measures[0].measure] or 0) / total) if total else None
        if query.limit is not None:
            if query.limit < 1: raise DatasetQueryError("limit must be positive")
            rows = rows[:query.limit]
        if query.column_axis:
            measure_names = [item.measure for item in query.measures]
            pivoted: dict[object, dict[str, object]] = {}
            for row in rows:
                key = row[query.row_axis]  # validated above
                target = pivoted.setdefault(key, {query.row_axis: key})
                column = str(row[query.column_axis]) if row[query.column_axis] is not None else "missing"
                for measure in measure_names:
                    target[f"{column}__{measure}"] = row[measure]
            rows = list(pivoted.values())
        contract = {"dataset": definition.dataset_key, "source": definition.object_name,
                    "filters": [item.__dict__ for item in query.filters], "group_by": list(grouping),
                    "axes": {"row": query.row_axis, "column": query.column_axis},
                    "measures": [item.__dict__ for item in query.measures], "order_by": query.order_by,
                    "descending": query.descending, "limit": query.limit, "share_of_total": query.share_of_total,
                    "snapshot_semantics": definition.snapshot_semantics,
                    "dimension_coverage": {field: list(assets) for field, assets in definition.dimension_coverage.items()}}
        return DatasetQueryResult(tuple(rows), {"status": "complete" if eligible_count else "none", "eligible_row_count": eligible_count, "observed_row_count": full_count, "full_universe_scanned": True, "output_intentionally_limited": query.limit is not None}, contract)


_JLL_FLOOR = re.compile(r"^(\d+)")


def _jll_floor(unidad: object) -> str | None:
    """JLL Apo nomenclature: final two digits identify the unit within its floor."""
    match = _JLL_FLOOR.match(str(unidad or "").strip())
    if match is None:
        return None
    digits = match.group(1)
    return digits[:-2] if len(digits) > 2 else digits
