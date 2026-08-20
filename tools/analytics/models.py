from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


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


@dataclass(frozen=True)
class MetricCatalog:
    version: int
    metrics: dict[str, MetricDefinition]

    def as_dict(self) -> dict[str, object]:
        return {
            "catalog_version": self.version,
            "metrics": {key: asdict(metric) for key, metric in self.metrics.items()},
        }
