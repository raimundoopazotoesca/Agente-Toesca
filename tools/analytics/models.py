from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal


class EntityType(StrEnum):
    FUND = "fund"
    ASSET = "asset"


class MetricNature(StrEnum):
    FLOW = "flow"
    POINT_IN_TIME = "point_in_time"
    RATIO = "ratio"
    OTHER = "other"


class Aggregation(StrEnum):
    SUM = "sum"
    AVG = "avg"
    LAST = "last"


@dataclass(frozen=True)
class EntityReference:
    """A canonical, typed entity selected by an upstream adapter.

    This has no database, provider, or natural-language-resolution dependency.
    """

    entity_id: str
    entity_type: EntityType


@dataclass(frozen=True)
class SemanticQuery:
    """Provider-neutral business request executed through a metric contract."""

    metric_id: str
    entities: tuple[EntityReference, ...]
    period_start: str
    period_end: str | None = None
    temporal_aggregation: Aggregation | None = None
    display_unit: str | None = None
    group_by: str | None = None
    order_by: str | None = None
    limit: int | None = None
    space_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityDefinition:
    """Canonical identity and aliases, always scoped by entity type."""

    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: tuple[str, ...] = ()
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass(frozen=True)
class AccessStrategy:
    kind: Literal["derived_kpi", "view_metric", "rollup_ratio_view", "fallback_chain"]


@dataclass(frozen=True)
class DerivedKpiAccess(AccessStrategy):
    entity_type: str
    kpi: str

    def __init__(self, entity_type: str, kpi: str):
        object.__setattr__(self, "kind", "derived_kpi")
        object.__setattr__(self, "entity_type", entity_type)
        object.__setattr__(self, "kpi", kpi)


@dataclass(frozen=True)
class ViewMetricAccess(AccessStrategy):
    view: str
    value_column: str

    def __init__(self, view: str, value_column: str):
        object.__setattr__(self, "kind", "view_metric")
        object.__setattr__(self, "view", view)
        object.__setattr__(self, "value_column", value_column)


@dataclass(frozen=True)
class SegmentedVacancyAccess(AccessStrategy):
    """Physical vacancy segmented through the existing authoritative view."""
    view: str
    entity_column: str
    asset_groups: dict
    source_labels: dict[str, tuple[str, ...]]
    measurement_units: dict[str, str]

    def __init__(self, view: str, entity_column: str, asset_groups: dict,
                 source_labels: dict[str, tuple[str, ...]], measurement_units: dict[str, str]):
        object.__setattr__(self, "kind", "segmented_vacancy")
        object.__setattr__(self, "view", view)
        object.__setattr__(self, "entity_column", entity_column)
        object.__setattr__(self, "asset_groups", {k: tuple(tuple(g) for g in v) for k, v in asset_groups.items()})
        object.__setattr__(self, "source_labels", {k: tuple(v) for k, v in source_labels.items()})
        object.__setattr__(self, "measurement_units", dict(measurement_units))


@dataclass(frozen=True)
class RollupRatioViewAccess(AccessStrategy):
    """Fund-level ratio computed as SUM(numerator)/SUM(denominator) over a
    shared entity-grain governed view (e.g. v_vacancia_activo), summed
    across the component entities that make up a fund.

    `asset_groups` maps fund_key -> an ORDERED tuple of candidate entity-key
    groups (no per-fund code branching — the group membership is data, not
    logic). For a given period, the first group with any valid component
    pair wins; later groups are only consulted for periods the earlier
    group is silent on. This lets a fund whose governed source changed
    representation over time (e.g. per-asset rent-roll rows in one era,
    a single fund-level manual total row in an earlier era) resolve to
    the right one per period, deterministically."""

    view: str
    entity_column: str
    asset_groups: dict
    numerator_column: str
    denominator_column: str
    exclude_column: str | None
    exclude_value: str | None

    def __init__(self, view: str, entity_column: str, asset_groups: dict, numerator_column: str,
                 denominator_column: str, exclude_column: str | None = None, exclude_value: str | None = None):
        object.__setattr__(self, "kind", "rollup_ratio_view")
        object.__setattr__(self, "view", view)
        object.__setattr__(self, "entity_column", entity_column)
        object.__setattr__(self, "asset_groups", {
            fund: tuple(tuple(group) for group in groups) for fund, groups in asset_groups.items()
        })
        object.__setattr__(self, "numerator_column", numerator_column)
        object.__setattr__(self, "denominator_column", denominator_column)
        object.__setattr__(self, "exclude_column", exclude_column)
        object.__setattr__(self, "exclude_value", exclude_value)


@dataclass(frozen=True)
class FallbackAccess(AccessStrategy):
    """Tries `primary` first; for any (entity, period) it does not cover,
    tries `fallback`. Deterministic precedence — primary always wins when
    it has a row, never averaged or merged with fallback for the same cell."""

    primary: AccessStrategy
    fallback: AccessStrategy

    def __init__(self, primary: AccessStrategy, fallback: AccessStrategy):
        object.__setattr__(self, "kind", "fallback_chain")
        object.__setattr__(self, "primary", primary)
        object.__setattr__(self, "fallback", fallback)


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    display_name: str
    description: str
    unit: str
    entity_grain: str
    period_grain: str
    source_kind: str
    access: AccessStrategy
    aggregation: str
    allowed_dimensions: tuple[str, ...]
    status: str
    related_metrics: tuple[str, ...]
    methodology: str
    display_unit: str | None = None
    nature: MetricNature = MetricNature.OTHER
    allowed_temporal_aggregations: tuple[Aggregation, ...] = ()

    @property
    def metric_id(self) -> str:
        return self.key

    @property
    def native_unit(self) -> str:
        return self.unit


@dataclass(frozen=True)
class MetricCatalog:
    version: int
    metrics: dict[str, MetricDefinition]

    def as_dict(self) -> dict[str, object]:
        return {
            "catalog_version": self.version,
            "metrics": {key: asdict(metric) for key, metric in self.metrics.items()},
        }
