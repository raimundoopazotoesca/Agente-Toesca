from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tools.analytics.models import (
    AccessStrategy, Aggregation, DerivedKpiAccess, FallbackAccess, MetricCatalog, MetricDefinition,
    MetricNature, RollupRatioViewAccess, ViewMetricAccess,
)


CATALOG_PATH = Path(__file__).with_name("catalog_v1.yaml")
_UNITS = {"pct_0_100", "m2", "ratio_0_1", "clp", "UF"}
# `display_unit` is presentation-only: it never changes the semantic value
# carried by evidence/claims, only how a bound fact is rendered for a human.
_DISPLAY_UNITS = {"percent"}
_DISPLAY_UNIT_SOURCES = {"percent": {"ratio_0_1"}}
_ENTITY_GRAINS = {"fund", "asset"}
_PERIOD_GRAINS = {"month"}
_SOURCE_KINDS = {"canonical", "breakdown", "alternative"}
_AGGREGATIONS = {"non_additive", "sum_compatible_scope"}
_NATURES = {item.value for item in MetricNature}
_TEMPORAL_AGGREGATIONS = {item.value for item in Aggregation}
_STATUSES = {"active"}
_REQUIRED = {
    "key", "display_name", "description", "unit", "entity_grain", "period_grain", "source_kind",
    "access", "aggregation", "allowed_dimensions", "status", "related_metrics", "methodology",
}
_PROHIBITED_VALUE_FIELDS = {"value", "valor", "current_value", "entities", "entity_values"}


class CatalogValidationError(ValueError):
    pass


def _invalid(message: str) -> CatalogValidationError:
    return CatalogValidationError(message)


def _access(raw: Any) -> AccessStrategy:
    if not isinstance(raw, dict):
        raise _invalid("malformed access strategy")
    kind = raw.get("kind")
    if kind == "derived_kpi" and set(raw) == {"kind", "entity_type", "kpi"}:
        return DerivedKpiAccess(entity_type=str(raw["entity_type"]), kpi=str(raw["kpi"]))
    if kind == "view_metric" and set(raw) == {"kind", "view", "value_column"}:
        return ViewMetricAccess(view=str(raw["view"]), value_column=str(raw["value_column"]))
    if kind == "rollup_ratio_view" and set(raw) <= {
        "kind", "view", "entity_column", "asset_groups", "numerator_column", "denominator_column",
        "exclude_column", "exclude_value",
    } and {"kind", "view", "entity_column", "asset_groups", "numerator_column", "denominator_column"} <= set(raw):
        asset_groups = raw["asset_groups"]
        if not isinstance(asset_groups, dict) or not asset_groups:
            raise _invalid("malformed access strategy: asset_groups must be a non-empty fund_key->groups map")
        for fund, groups in asset_groups.items():
            if not isinstance(fund, str) or not isinstance(groups, list) or not groups:
                raise _invalid("malformed access strategy: asset_groups values must be non-empty lists of groups")
            for group in groups:
                if not isinstance(group, list) or not group or not all(isinstance(item, str) for item in group):
                    raise _invalid("malformed access strategy: each asset group must be a non-empty list of entity keys")
        return RollupRatioViewAccess(
            view=str(raw["view"]), entity_column=str(raw["entity_column"]), asset_groups=asset_groups,
            numerator_column=str(raw["numerator_column"]), denominator_column=str(raw["denominator_column"]),
            exclude_column=(str(raw["exclude_column"]) if raw.get("exclude_column") is not None else None),
            exclude_value=(str(raw["exclude_value"]) if raw.get("exclude_value") is not None else None),
        )
    if kind == "fallback_chain" and set(raw) == {"kind", "primary", "fallback"}:
        return FallbackAccess(primary=_access(raw["primary"]), fallback=_access(raw["fallback"]))
    raise _invalid("malformed access strategy")


def _metric(raw: Any) -> MetricDefinition:
    if not isinstance(raw, dict) or _REQUIRED - raw.keys() or _PROHIBITED_VALUE_FIELDS & raw.keys():
        raise _invalid("malformed metric definition")
    for field, allowed in (
        ("unit", _UNITS), ("entity_grain", _ENTITY_GRAINS), ("period_grain", _PERIOD_GRAINS),
        ("source_kind", _SOURCE_KINDS), ("aggregation", _AGGREGATIONS), ("status", _STATUSES),
    ):
        if raw[field] not in allowed:
            raise _invalid(f"malformed metric definition: invalid {field}")
    if not isinstance(raw["allowed_dimensions"], list) or not isinstance(raw["related_metrics"], list):
        raise _invalid("malformed metric definition: dimensions and relations must be lists")
    display_unit = raw.get("display_unit")
    if display_unit is not None:
        if display_unit not in _DISPLAY_UNITS:
            raise _invalid("malformed metric definition: invalid display_unit")
        if raw["unit"] not in _DISPLAY_UNIT_SOURCES[display_unit]:
            raise _invalid("malformed metric definition: display_unit incompatible with unit")
    nature = raw.get("nature", "other")
    aggregations = raw.get("allowed_temporal_aggregations", [])
    if nature not in _NATURES or not isinstance(aggregations, list) or any(item not in _TEMPORAL_AGGREGATIONS for item in aggregations):
        raise _invalid("malformed metric definition: invalid semantic aggregation contract")
    if nature != MetricNature.FLOW.value and Aggregation.SUM.value in aggregations:
        raise _invalid("malformed metric definition: SUM requires flow nature")
    return MetricDefinition(
        key=str(raw["key"]), display_name=str(raw["display_name"]), description=str(raw["description"]),
        unit=raw["unit"], entity_grain=raw["entity_grain"], period_grain=raw["period_grain"],
        source_kind=raw["source_kind"], access=_access(raw["access"]), aggregation=raw["aggregation"],
        allowed_dimensions=tuple(raw["allowed_dimensions"]), status=raw["status"],
        related_metrics=tuple(raw["related_metrics"]), methodology=str(raw["methodology"]),
        display_unit=display_unit,
        nature=MetricNature(nature),
        allowed_temporal_aggregations=tuple(Aggregation(item) for item in aggregations),
    )


def load_metric_catalog(path: Path | None = None) -> MetricCatalog:
    path = path or CATALOG_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("catalog_version") != 1 or not isinstance(raw.get("metrics"), list):
        raise _invalid("malformed catalog")
    if not raw["metrics"]:
        raise _invalid("catalog must define at least one metric")
    metrics = [_metric(item) for item in raw["metrics"]]
    keys = [metric.key for metric in metrics]
    if len(keys) != len(set(keys)) or not all(keys):
        raise _invalid("duplicate or empty metric key")
    known = set(keys)
    for metric in metrics:
        unknown = set(metric.related_metrics) - known
        if unknown:
            raise _invalid(f"unknown related metric: {sorted(unknown)[0]}")
    return MetricCatalog(version=1, metrics={metric.key: metric for metric in sorted(metrics, key=lambda item: item.key)})
