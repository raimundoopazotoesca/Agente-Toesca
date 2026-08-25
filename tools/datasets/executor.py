"""Deterministic executor for declarative governed dataset queries."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        if any(field not in definition.dimensions and field not in visible_fields for field in query.group_by):
            raise DatasetQueryError("group_by field is not declared by dataset")
        if len(query.group_by) > 2:
            raise DatasetQueryError("at most two visible dimensions are supported")
        where, params = ["is_current=1"], []
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
            aggregate = {"sum": "SUM", "count": "COUNT", "distinct_count": "COUNT(DISTINCT", "avg": "AVG"}[item.aggregation]
            expr = f'{aggregate}("{field}")' if item.aggregation != "distinct_count" else f'COUNT(DISTINCT "{field}")'
            expressions.append(f'{expr} AS "{item.measure}"')
        select_dimensions = [f'"{field}"' for field in query.group_by]
        sql = f'SELECT {", ".join(select_dimensions + expressions)} FROM "{definition.object_name}" WHERE {" AND ".join(where)}'
        if query.group_by: sql += " GROUP BY " + ", ".join(select_dimensions)
        if query.order_by:
            if query.order_by not in {m.measure for m in query.measures}: raise DatasetQueryError("order_by must name a selected measure")
            sql += f' ORDER BY "{query.order_by}" {"DESC" if query.descending else "ASC"}'
        with self._sandbox.connect() as conn:
            eligible_count = conn.execute(f'SELECT COUNT(*) FROM "{definition.object_name}" WHERE {" AND ".join(where)}', params).fetchone()[0]
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
        return DatasetQueryResult(tuple(rows), {"status": "complete" if eligible_count else "none", "eligible_row_count": eligible_count, "observed_row_count": full_count, "full_universe_scanned": True, "output_intentionally_limited": query.limit is not None}, {"dataset": definition.dataset_key, "source": definition.object_name, "filters": [item.__dict__ for item in query.filters], "group_by": list(query.group_by), "measures": [item.__dict__ for item in query.measures]})
