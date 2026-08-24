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
    kind: Literal["derived_kpi", "view_metric"]


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
