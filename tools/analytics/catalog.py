from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tools.analytics.models import (
    AccessStrategy, AccessVariant, Aggregation, DerivedKpiAccess, DerivedKpiVariantSource, DimensionedAccess,
    DimensionSpec, FallbackAccess, MetricCatalog, MetricDefinition, MetricNature, MonetaryConversionColumns,
    RollupRatioViewAccess, SegmentedVacancyAccess, TableVariantSource, ViewMetricAccess,
)


CATALOG_PATH = Path(__file__).with_name("catalog_v1.yaml")
_UNITS = {"pct_0_100", "m2", "ratio_0_1", "clp", "UF", "cuotas"}
# `display_unit` is presentation-only: it never changes the semantic value
# carried by evidence/claims, only how a bound fact is rendered for a human.
_DISPLAY_UNITS = {"percent"}
_DISPLAY_UNIT_SOURCES = {"percent": {"ratio_0_1"}}
_ENTITY_GRAINS = {"fund", "asset", "series", "credit"}
_SCOPES = {"series", "credit", "fund_template"}
_TEMPORAL_CONTRACTS = {"period_point", "as_of", "period_flow", "event"}
_TEMPORAL_COMPLETENESS = {"dense", "event"}
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
    if kind == "segmented_vacancy" and set(raw) == {"kind", "view", "entity_column", "asset_groups", "source_labels", "measurement_units"}:
        labels, units, groups = raw["source_labels"], raw["measurement_units"], raw["asset_groups"]
        if (not isinstance(labels, dict) or not labels or not isinstance(units, dict)
                or set(labels) != set(units) or not all(isinstance(v, list) and v for v in labels.values())
                or not isinstance(groups, dict)):
            raise _invalid("malformed segmented vacancy access")
        return SegmentedVacancyAccess(str(raw["view"]), str(raw["entity_column"]), groups,
                                      {str(k): tuple(map(str, v)) for k, v in labels.items()},
                                      {str(k): str(v) for k, v in units.items()})
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
    if kind == "dimensioned":
        return _dimensioned_access(raw)
    raise _invalid("malformed access strategy")


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: Any, what: str) -> str:
    """Every table/column name reaching SQL is validated here, once.

    The dimensioned strategy interpolates identifiers into SQL (SQLite cannot
    bind them as parameters), so the catalog -- not the caller -- is the trust
    boundary: anything that is not a bare identifier is a catalog error.
    """
    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise _invalid(f"malformed access strategy: invalid {what}")
    return value


def _variant_source(raw: Any) -> DerivedKpiVariantSource | TableVariantSource:
    if not isinstance(raw, dict):
        raise _invalid("malformed access strategy: variant source must be a mapping")
    kind = raw.get("kind")
    if kind == "derived_kpi" and set(raw) <= {"kind", "entity_type", "kpi", "variante"}:
        return DerivedKpiVariantSource(
            entity_type=_identifier(raw.get("entity_type"), "entity_type"),
            kpi=_identifier(raw.get("kpi"), "kpi"),
            variante=(str(raw["variante"]) if raw.get("variante") is not None else None),
        )
    allowed = {"kind", "table", "entity_column", "value_column", "temporal", "period_column",
               "date_column", "filters", "dedupe_columns", "provenance_columns", "conversion"}
    if kind != "table" or not set(raw) <= allowed:
        raise _invalid("malformed access strategy: unknown variant source")
    temporal = raw.get("temporal")
    if temporal not in _TEMPORAL_CONTRACTS:
        raise _invalid("malformed access strategy: invalid temporal contract")
    filters = raw.get("filters") or {}
    if not isinstance(filters, dict):
        raise _invalid("malformed access strategy: filters must be a mapping")
    conversion_raw = raw.get("conversion")
    conversion = None
    if conversion_raw is not None:
        if not isinstance(conversion_raw, dict) or set(conversion_raw) != {
            "reference_column", "from_unit", "to_unit", "temporal_basis"
        }:
            raise _invalid("malformed access strategy: invalid conversion columns")
        conversion = MonetaryConversionColumns(
            reference_column=_identifier(conversion_raw["reference_column"], "reference_column"),
            from_unit=str(conversion_raw["from_unit"]), to_unit=str(conversion_raw["to_unit"]),
            temporal_basis=str(conversion_raw["temporal_basis"]),
        )
    period_column = raw.get("period_column")
    date_column = raw.get("date_column")
    if period_column is None and date_column is None:
        raise _invalid("malformed access strategy: a period or date column is required")
    if temporal == "event" and date_column is None:
        raise _invalid("malformed access strategy: event contract requires a date column")
    return TableVariantSource(
        table=_identifier(raw.get("table"), "table"),
        entity_column=_identifier(raw.get("entity_column"), "entity_column"),
        value_column=_identifier(raw.get("value_column"), "value_column"),
        temporal=temporal,
        period_column=_identifier(period_column, "period_column") if period_column is not None else None,
        date_column=_identifier(date_column, "date_column") if date_column is not None else None,
        filters={_identifier(column, "filter column"): (None if value is None else str(value))
                 for column, value in filters.items()},
        dedupe_columns=tuple(_identifier(item, "dedupe column") for item in raw.get("dedupe_columns") or ()),
        provenance_columns=tuple(_identifier(item, "provenance column") for item in raw.get("provenance_columns") or ()),
        conversion=conversion,
    )


def _dimensioned_access(raw: dict) -> DimensionedAccess:
    allowed = {"kind", "scope", "dimensions", "variants", "entity_key_template", "observed_horizon"}
    if not set(raw) <= allowed or raw.get("scope") not in _SCOPES:
        raise _invalid("malformed access strategy: invalid dimensioned scope")
    dimensions: list[DimensionSpec] = []
    for item in raw.get("dimensions") or []:
        if not isinstance(item, dict) or set(item) - {"name", "values", "default"} or not isinstance(item.get("values"), list) \
                or not item["values"] or not all(isinstance(value, str) and value for value in item["values"]):
            raise _invalid("malformed access strategy: invalid dimension spec")
        default = item.get("default")
        if default is not None and default not in item["values"]:
            raise _invalid("malformed access strategy: dimension default is not an allowed value")
        dimensions.append(DimensionSpec(_identifier(item.get("name"), "dimension name"),
                                        tuple(item["values"]), default))
    names = [dimension.name for dimension in dimensions]
    if len(names) != len(set(names)):
        raise _invalid("malformed access strategy: duplicate dimension")
    variants_raw = raw.get("variants")
    if not isinstance(variants_raw, list) or not variants_raw:
        raise _invalid("malformed access strategy: dimensioned access needs at least one variant")
    variants: list[AccessVariant] = []
    seen_values: list[tuple[tuple[str, str], ...]] = []
    for item in variants_raw:
        if not isinstance(item, dict) or set(item) - {"values", "source"}:
            raise _invalid("malformed access strategy: invalid variant")
        values = item.get("values") or {}
        if not isinstance(values, dict) or set(values) != set(names):
            raise _invalid("malformed access strategy: variant must bind every declared dimension")
        for name, value in values.items():
            spec = next(dimension for dimension in dimensions if dimension.name == name)
            if value not in spec.values:
                raise _invalid(f"malformed access strategy: undeclared value for dimension {name}")
        key = tuple(sorted((str(name), str(value)) for name, value in values.items()))
        if key in seen_values:
            raise _invalid("malformed access strategy: duplicate variant selector")
        seen_values.append(key)
        variants.append(AccessVariant(key, _variant_source(item.get("source"))))
    horizon_raw = raw.get("observed_horizon")
    horizon = _variant_source(horizon_raw) if horizon_raw is not None else None
    if horizon is not None and not isinstance(horizon, DerivedKpiVariantSource):
        raise _invalid("malformed access strategy: observed_horizon must be a derived_kpi source")
    template = raw.get("entity_key_template")
    if (raw["scope"] == "fund_template") != (template is not None):
        raise _invalid("malformed access strategy: entity_key_template belongs to fund_template scope")
    if template is not None and not isinstance(template, str):
        raise _invalid("malformed access strategy: invalid entity_key_template")
    return DimensionedAccess(str(raw["scope"]), tuple(dimensions), tuple(variants), template, horizon)


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
    completeness = raw.get("temporal_completeness", "dense")
    if completeness not in _TEMPORAL_COMPLETENESS:
        raise _invalid("malformed metric definition: invalid temporal_completeness")
    if completeness == "event" and nature != MetricNature.FLOW.value:
        raise _invalid("malformed metric definition: event completeness requires flow nature")
    return MetricDefinition(
        key=str(raw["key"]), display_name=str(raw["display_name"]), description=str(raw["description"]),
        unit=raw["unit"], entity_grain=raw["entity_grain"], period_grain=raw["period_grain"],
        source_kind=raw["source_kind"], access=_access(raw["access"]), aggregation=raw["aggregation"],
        allowed_dimensions=tuple(raw["allowed_dimensions"]), status=raw["status"],
        related_metrics=tuple(raw["related_metrics"]), methodology=str(raw["methodology"]),
        display_unit=display_unit,
        nature=MetricNature(nature),
        allowed_temporal_aggregations=tuple(Aggregation(item) for item in aggregations),
        temporal_completeness=completeness,
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
