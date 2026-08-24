"""Catalog-derived affordances for governed analytics operations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.analytics.models import DerivedKpiAccess, MetricCatalog, MetricDefinition, ViewMetricAccess


def capability_metric_keys(catalog: MetricCatalog) -> dict[str, tuple[str, ...]]:
    """Return active metrics eligible for each public operation and grain."""
    active = tuple(metric for metric in catalog.metrics.values() if metric.status == "active")
    return {
        "fund_lookup": tuple(metric.key for metric in active if metric.entity_grain == "fund"),
        "asset_lookup": tuple(metric.key for metric in active if metric.entity_grain == "asset"),
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
