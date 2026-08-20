"""Catalog-derived affordances for governed analytics operations."""
from __future__ import annotations

from tools.analytics.models import MetricCatalog


def capability_metric_keys(catalog: MetricCatalog) -> dict[str, tuple[str, ...]]:
    """Return active metrics eligible for each public operation and grain."""
    active = tuple(metric for metric in catalog.metrics.values() if metric.status == "active")
    return {
        "fund_lookup": tuple(metric.key for metric in active if metric.entity_grain == "fund"),
        "asset_lookup": tuple(metric.key for metric in active if metric.entity_grain == "asset"),
        "asset_breakdown": tuple(
            metric.key for metric in active
            if metric.entity_grain == "asset"
            and metric.source_kind == "breakdown"
            and {"fund", "asset"}.issubset(metric.allowed_dimensions)
        ),
    }
