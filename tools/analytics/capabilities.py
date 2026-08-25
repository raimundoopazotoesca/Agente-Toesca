"""Catalog-derived affordances for governed analytics operations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.analytics.models import (
    DerivedKpiAccess, DerivedKpiVariantSource, DimensionedAccess, MetricCatalog, MetricDefinition,
    TableVariantSource, ViewMetricAccess,
)


def capability_metric_keys(catalog: MetricCatalog) -> dict[str, tuple[str, ...]]:
    """Return active metrics eligible for each public operation and grain."""
    active = tuple(metric for metric in catalog.metrics.values() if metric.status == "active")
    return {
        # A dimensioned metric is reached through its own capability whatever
        # its grain, because it needs the dimension arguments (basis, window,
        # flow type) that the plain lookups have no contract for.
        "fund_lookup": tuple(metric.key for metric in active
                             if metric.entity_grain == "fund" and not isinstance(metric.access, DimensionedAccess)),
        "asset_lookup": tuple(metric.key for metric in active if metric.entity_grain == "asset"),
        "dimensional_lookup": tuple(metric.key for metric in active if isinstance(metric.access, DimensionedAccess)),
        "asset_breakdown": tuple(
            metric.key for metric in active
            # Purely dimensional: a metric is breakdownable when its grain is
            # the asset and its contract permits both the fund and the asset
            # dimension. `source_kind` describes the authority of the datum,
            # not which operation is allowed over it -- gating on it would
            # wrongly exclude canonical asset-grain metrics (LTV, NOI).
            if metric.entity_grain == "asset"
            and {"fund", "asset"}.issubset(metric.allowed_dimensions)
        ),
    }


def metric_period_bounds(db_path: Path, metric: MetricDefinition) -> tuple[str, str] | None:
    """Observed (first, last) month for one metric, derived from its own
    catalog access strategy -- never a hand-written per-metric range.

    A governed capability requires an explicit `period`; without knowing which
    months exist the model cannot form a valid call and falls back to raw
    exploration. Returns None whenever the range cannot be observed (missing
    database, missing object, no rows): the affordance degrades to the metric
    list, it never guesses.
    """
    access = metric.access
    if isinstance(access, DerivedKpiAccess):
        sql = "SELECT MIN(periodo), MAX(periodo) FROM derived_kpi WHERE entidad_tipo=? AND kpi=?"
        params: tuple[object, ...] = (access.entity_type, access.kpi)
    elif isinstance(access, ViewMetricAccess):
        sql, params = f"SELECT MIN(periodo), MAX(periodo) FROM {access.view}", ()
    elif isinstance(access, DimensionedAccess):
        return _dimensioned_bounds(db_path, access)
    else:
        return None
    try:
        connection = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        first, last = connection.execute(sql, params).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return (str(first), str(last)) if first and last else None


def _dimensioned_bounds(db_path: Path, access: DimensionedAccess) -> tuple[str, str] | None:
    """Observed range of a dimensioned metric: the union across its variants.

    Same purpose and same fail-open behaviour as the simple case -- the model
    needs to know which months exist before it can form a valid call, and a
    range that cannot be observed degrades to no hint rather than a guess.
    """
    try:
        connection = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    bounds: list[str] = []
    try:
        for variant in access.variants:
            source = variant.source
            if isinstance(source, DerivedKpiVariantSource):
                clause = "variante IS NULL" if source.variante is None else "variante=?"
                params: tuple[object, ...] = (source.entity_type, source.kpi)
                if source.variante is not None:
                    params = params + (source.variante,)
                sql = ("SELECT MIN(periodo), MAX(periodo) FROM derived_kpi "
                       f"WHERE entidad_tipo=? AND kpi=? AND {clause}")
            elif isinstance(source, TableVariantSource):
                expression = source.period_column or f"substr({source.date_column},1,7)"
                sql = f"SELECT MIN({expression}), MAX({expression}) FROM {source.table}"
                params = ()
            else:  # pragma: no cover -- guarded by the catalog loader
                continue
            try:
                first, last = connection.execute(sql, params).fetchone()
            except sqlite3.Error:
                continue
            if first and last:
                bounds.extend([str(first), str(last)])
    finally:
        connection.close()
    return (min(bounds), max(bounds)) if bounds else None
