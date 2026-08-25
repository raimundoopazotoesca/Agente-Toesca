from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal


class EntityType(StrEnum):
    FUND = "fund"
    ASSET = "asset"
    # A share class of a fund. It is NOT a free-standing business entity: it
    # is always reached through its fund plus the `series` dimension (see
    # DimensionedAccess/`series` scope). It carries its own canonical DB
    # identity (``dim_serie.nemotecnico``) purely so a bound fact can never
    # collide between TRI A / TRI C / TRI I.
    SERIES = "series"
    # One credit facility of a fund (``dim_credito.credito_key``).
    CREDIT = "credit"


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
    # Generic, catalog-declared semantic dimensions selected for this request
    # (e.g. valuation_basis=book, return_window=trailing_12m, flow_type=
    # dividend). Kept as a sorted tuple of pairs so SemanticQuery stays frozen
    # and hashable. There is no per-metric field here on purpose: a new
    # dimension is a catalog row, never a new dataclass attribute.
    dimensions: tuple[tuple[str, str], ...] = ()
    # Sub-entity selector inside the scope entity (a series letter, a credit
    # key). None means "every applicable sub-entity", which is what turns a
    # scalar lookup into a governed breakdown without a second capability.
    selector: str | None = None

    def dimension(self, name: str) -> str | None:
        return dict(self.dimensions).get(name)


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
class DimensionSpec:
    """One catalog-declared semantic dimension of a metric.

    ``default`` is what makes a dimension optional. A dimension WITHOUT a
    default is required: omitting it is a fail-closed
    :class:`SemanticQueryError` carrying the allowed values, which the runtime
    turns into a clarification instead of silently picking a variant. That is
    the whole mechanism behind "¿Cuál es la TIR de TRI?" asking back rather
    than choosing bursátil/contable or since-inception/U12M on its own.
    """

    name: str
    values: tuple[str, ...]
    default: str | None = None


@dataclass(frozen=True)
class MonetaryConversionColumns:
    """Declares that a row carries its own governed conversion reference.

    Only used to attach a display-only ``presentation_conversion`` to a fact
    (see analytics/monetary.py). The stored native value is never modified.
    """

    reference_column: str
    from_unit: str
    to_unit: str
    temporal_basis: str


@dataclass(frozen=True)
class DerivedKpiVariantSource:
    """A persisted, already-validated ``derived_kpi`` observation.

    Exposed as-is: a FACTORED/PERSISTED KPI is never recomputed from cash
    flows by this layer, only located and bound.
    """

    kind: str
    entity_type: str
    kpi: str
    variante: str | None

    def __init__(self, entity_type: str, kpi: str, variante: str | None = None):
        object.__setattr__(self, "kind", "derived_kpi")
        object.__setattr__(self, "entity_type", entity_type)
        object.__setattr__(self, "kpi", kpi)
        object.__setattr__(self, "variante", variante)


@dataclass(frozen=True)
class TableVariantSource:
    """A raw table / governed view read under an explicit temporal contract.

    ``temporal`` is the contract, not an implementation detail:

    * ``period_point``  — one point-in-time observation per (entity, period)
      inside the requested range; the newest row of that period wins.
    * ``as_of``         — the single newest observation at or before the end
      of the requested range, whatever its own period is. The fact keeps the
      period it was really observed in, so a stale capital figure is reported
      "a septiembre de 2021", never implied to be current.
    * ``period_flow``   — one flow amount per (entity, period), dense.
    * ``event``         — zero or more dated events per period; absence of an
      event is NOT a gap and NOT a zero.
    """

    kind: str
    table: str
    entity_column: str
    value_column: str
    temporal: str
    period_column: str | None
    date_column: str | None
    filters: tuple[tuple[str, str | None], ...]
    dedupe_columns: tuple[str, ...]
    provenance_columns: tuple[str, ...]
    conversion: MonetaryConversionColumns | None

    def __init__(self, table: str, entity_column: str, value_column: str, temporal: str,
                 period_column: str | None = None, date_column: str | None = None,
                 filters: dict[str, str | None] | None = None, dedupe_columns: tuple[str, ...] = (),
                 provenance_columns: tuple[str, ...] = (), conversion: MonetaryConversionColumns | None = None):
        object.__setattr__(self, "kind", "table")
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "entity_column", entity_column)
        object.__setattr__(self, "value_column", value_column)
        object.__setattr__(self, "temporal", temporal)
        object.__setattr__(self, "period_column", period_column)
        object.__setattr__(self, "date_column", date_column)
        object.__setattr__(self, "filters", tuple(sorted((filters or {}).items())))
        object.__setattr__(self, "dedupe_columns", tuple(dedupe_columns))
        object.__setattr__(self, "provenance_columns", tuple(provenance_columns))
        object.__setattr__(self, "conversion", conversion)


@dataclass(frozen=True)
class AccessVariant:
    """One (dimension values) -> source binding of a DimensionedAccess."""

    values: tuple[tuple[str, str], ...]
    source: DerivedKpiVariantSource | TableVariantSource


@dataclass(frozen=True)
class DimensionedAccess(AccessStrategy):
    """The generic access strategy behind the fund financial surface.

    ONE strategy covers every new metric family because the only things that
    change between them are data, not code: which sub-entities the metric is
    observed over (``scope``), which semantic dimensions select a source
    (``dimensions`` + ``variants``), and which temporal contract that source
    obeys. There is deliberately no per-KPI branch anywhere downstream.

    ``scope``:
      * ``series``        — sub-entities come from ``dim_serie`` for the fund.
      * ``credit``        — sub-entities come from ``dim_credito`` for the fund.
      * ``fund_template`` — a single synthetic source key derived from the fund
        (``entity_key_template``), reported under the fund's own identity.
    """

    scope: str
    dimensions: tuple[DimensionSpec, ...]
    variants: tuple[AccessVariant, ...]
    entity_key_template: str | None
    observed_horizon: DerivedKpiVariantSource | None

    def __init__(self, scope: str, dimensions: tuple[DimensionSpec, ...], variants: tuple[AccessVariant, ...],
                 entity_key_template: str | None = None, observed_horizon: DerivedKpiVariantSource | None = None):
        object.__setattr__(self, "kind", "dimensioned")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "dimensions", tuple(dimensions))
        object.__setattr__(self, "variants", tuple(variants))
        object.__setattr__(self, "entity_key_template", entity_key_template)
        object.__setattr__(self, "observed_horizon", observed_horizon)

    def select(self, selected: dict[str, str]) -> AccessVariant | None:
        for variant in self.variants:
            if all(selected.get(name) == value for name, value in variant.values):
                return variant
        return None


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
    # ``dense``: every month in a requested range must be observed before an
    # aggregation is allowed (the original, unchanged contract -- a missing
    # month is a coverage gap).
    # ``event``: the metric is a discrete event stream (a distribution is paid
    # on a date or not at all), so a month with no row is NOT a gap. Summing
    # observed events over a range is then valid; it is still never a licence
    # to treat an absent event as a zero.
    temporal_completeness: str = "dense"

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
