"""Fund Financial Surface v1 -- metric contracts, source authority and
temporal semantics of the series/credit financial metrics.

These tests are deterministic and run against the real, READ-ONLY knowledge
database: the point of the surface is that specific governed figures are
reachable through a governed contract, so pinning representative values is the
only way to prove the contract resolves to the right source.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.analytics.catalog import CatalogValidationError, load_metric_catalog
from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError
from tools.analytics.models import DimensionedAccess, MetricNature

DB = Path("memory/agente_toesca_v2.db")

FINANCIAL_METRICS = (
    "dividend_yield_serie", "tir_serie", "valor_cuota_serie", "distribucion_por_cuota_serie",
    "capital_suscrito_serie", "cuotas_en_circulacion_serie", "patrimonio_contable_serie",
    "patrimonio_bursatil_serie", "amortizacion_capital_fondo", "amortizacion_capital_credito",
)


def run(**kwargs):
    return AnalyticsExecutor(DB).execute(AnalyticsQueryRequest(**kwargs))


def one(**kwargs):
    result = run(**kwargs)
    assert len(result.rows) == 1, [row.entity_id for row in result.rows]
    return result.rows[0]


# --------------------------------------------------------------------------
# Metric definitions and contracts
# --------------------------------------------------------------------------

def test_every_financial_metric_is_published_through_the_generic_dimensioned_strategy():
    catalog = load_metric_catalog().metrics
    for key in FINANCIAL_METRICS:
        assert key in catalog, key
        assert isinstance(catalog[key].access, DimensionedAccess), key


def test_temporal_contract_forbids_summing_point_in_time_and_ratio_metrics():
    catalog = load_metric_catalog().metrics
    for key in ("valor_cuota_serie", "capital_suscrito_serie", "cuotas_en_circulacion_serie",
                "patrimonio_contable_serie", "patrimonio_bursatil_serie"):
        assert catalog[key].nature is MetricNature.POINT_IN_TIME
        assert catalog[key].allowed_temporal_aggregations == ()
    for key in ("dividend_yield_serie", "tir_serie"):
        assert catalog[key].nature is MetricNature.RATIO
        assert catalog[key].allowed_temporal_aggregations == ()


def test_summing_a_unit_value_across_months_is_rejected_by_contract():
    with pytest.raises(SemanticQueryError) as exc:
        run(metric="valor_cuota_serie", funds=("TRI",), period="2025-03", period_end="2025-12",
            selector="A", dimensions=(("valuation_basis", "book"),), aggregation="sum")
    assert exc.value.code == "invalid_aggregation"


def test_book_unit_value_authority_is_the_raw_snapshot_never_the_stale_derived_kpi():
    """`derived_kpi.valor_cuota_libro` still holds a handful of stale rows for
    the same concept. The catalog must not reference them at all, otherwise
    two sources would silently disagree about the same figure."""
    catalog = load_metric_catalog().metrics
    access = catalog["valor_cuota_serie"].access
    tables = {variant.source.table for variant in access.variants}
    assert tables == {"raw_valor_cuota_contable", "raw_valor_cuota_bursatil"}
    for variant in access.variants:
        assert getattr(variant.source, "kpi", None) is None


def test_catalog_rejects_a_variant_that_leaves_a_dimension_unbound(tmp_path):
    bad = tmp_path / "catalog.yaml"
    bad.write_text("""catalog_version: 1
metrics:
- key: broken
  display_name: Broken
  description: broken
  unit: UF
  entity_grain: series
  period_grain: month
  source_kind: canonical
  access:
    kind: dimensioned
    scope: series
    dimensions:
      - {name: valuation_basis, values: [book, market]}
    variants:
      - values: {}
        source: {kind: derived_kpi, entity_type: serie, kpi: dy, variante: contable}
  aggregation: non_additive
  allowed_dimensions: [fund, series, period]
  status: active
  related_metrics: []
  methodology: broken
  nature: point_in_time
  allowed_temporal_aggregations: []
""", encoding="utf-8")
    with pytest.raises(CatalogValidationError):
        load_metric_catalog(bad)


def test_catalog_rejects_a_non_identifier_table_name(tmp_path):
    bad = tmp_path / "catalog.yaml"
    bad.write_text("""catalog_version: 1
metrics:
- key: broken
  display_name: Broken
  description: broken
  unit: UF
  entity_grain: series
  period_grain: month
  source_kind: canonical
  access:
    kind: dimensioned
    scope: series
    dimensions: []
    variants:
      - values: {}
        source:
          kind: table
          table: "raw_x; DROP TABLE dim_fondo"
          entity_column: nemotecnico
          value_column: cuotas
          temporal: as_of
          period_column: periodo
  aggregation: non_additive
  allowed_dimensions: [fund, series, period]
  status: active
  related_metrics: []
  methodology: broken
  nature: point_in_time
  allowed_temporal_aggregations: []
""", encoding="utf-8")
    with pytest.raises(CatalogValidationError):
        load_metric_catalog(bad)


# --------------------------------------------------------------------------
# Series as a dimension
# --------------------------------------------------------------------------

def test_series_selector_resolves_to_its_own_canonical_identity_without_collisions():
    rows = run(metric="tir_serie", funds=("TRI",), period="2026-06",
               dimensions=(("return_basis", "market"), ("return_window", "since_inception"))).rows
    assert [row.entity_id for row in rows] == ["CFITOERI1A", "CFITOERI1C", "CFITOERI1I"]
    assert [row.dimensions["series"] for row in rows] == ["A", "C", "I"]
    assert len({row.value for row in rows}) == 3


def test_series_selector_accepts_the_letter_and_the_nemotecnico():
    by_letter = one(metric="tir_serie", funds=("TRI",), period="2026-06", selector="I",
                    dimensions=(("return_basis", "market"), ("return_window", "since_inception")))
    by_key = one(metric="tir_serie", funds=("TRI",), period="2026-06", selector="CFITOERI1I",
                 dimensions=(("return_basis", "market"), ("return_window", "since_inception")))
    assert by_letter.entity_id == by_key.entity_id == "CFITOERI1I"
    assert by_letter.value == by_key.value


def test_unknown_series_fails_closed_instead_of_falling_back_to_the_fund():
    with pytest.raises(SemanticQueryError) as exc:
        run(metric="tir_serie", funds=("TRI",), period="2026-06", selector="Z",
            dimensions=(("return_basis", "market"), ("return_window", "since_inception")))
    assert exc.value.code == "unknown_selector"


# --------------------------------------------------------------------------
# Basis / window dimensions and ambiguity
# --------------------------------------------------------------------------

def test_dividend_yield_resolves_each_basis_to_its_own_persisted_variant():
    market = one(metric="dividend_yield_serie", funds=("TRI",), period="2026-06", selector="A",
                 dimensions=(("valuation_basis", "market"),))
    book = one(metric="dividend_yield_serie", funds=("TRI",), period="2026-03", selector="A",
               dimensions=(("valuation_basis", "book"),))
    assert market.value == pytest.approx(0.0264, abs=1e-4)
    assert market.provenance["variante"] == "bursatil"
    assert book.value == pytest.approx(0.0215, abs=1e-4)
    assert book.provenance["variante"] == "contable"


def test_tir_resolves_basis_and_window_to_the_persisted_kpi_without_recomputing():
    since = one(metric="tir_serie", funds=("TRI",), period="2026-06", selector="A",
                dimensions=(("return_basis", "market"), ("return_window", "since_inception")))
    trailing = one(metric="tir_serie", funds=("TRI",), period="2026-06", selector="A",
                   dimensions=(("return_basis", "market"), ("return_window", "trailing_12m")))
    assert since.value == pytest.approx(-0.0729, abs=1e-4)
    assert since.provenance["kpi"] == "tir_bursatil_desde_inicio"
    assert since.provenance["authority"] == "persisted_canonical_kpi"
    assert trailing.value == pytest.approx(0.0078, abs=1e-4)
    assert trailing.provenance["kpi"] == "tir_bursatil_u12m"


def test_a_bare_tir_request_fails_closed_with_the_options_it_needs():
    with pytest.raises(SemanticQueryError) as exc:
        run(metric="tir_serie", funds=("TRI",), period="2026-06", selector="A")
    assert exc.value.code == "dimension_required"
    missing = {item["dimension"]: item["allowed_values"] for item in exc.value.metadata["missing_dimensions"]}
    assert missing == {"return_basis": ["market", "book"],
                       "return_window": ["since_inception", "trailing_12m", "ytd"]}


def test_an_unavailable_basis_window_combination_is_rejected_not_substituted():
    with pytest.raises(SemanticQueryError) as exc:
        run(metric="tir_serie", funds=("TRI",), period="2026-06", selector="A",
            dimensions=(("return_basis", "market"), ("return_window", "ytd")))
    assert exc.value.code == "unavailable_dimension_combination"


def test_an_unknown_dimension_value_is_rejected():
    with pytest.raises(SemanticQueryError) as exc:
        run(metric="dividend_yield_serie", funds=("TRI",), period="2026-06", selector="A",
            dimensions=(("valuation_basis", "nominal"),))
    assert exc.value.code == "unknown_dimension_value"


# --------------------------------------------------------------------------
# Unit values
# --------------------------------------------------------------------------

def test_book_unit_value_is_the_eeff_close_with_a_governed_uf_reference():
    row = one(metric="valor_cuota_serie", funds=("TRI",), period="2026-03", selector="A",
              dimensions=(("valuation_basis", "book"),))
    assert row.value == pytest.approx(32341.6845)
    assert row.unit == "clp"
    assert row.provenance["source"] == "raw_valor_cuota_contable"
    conversion = row.dimensions["presentation_conversion"]
    assert conversion["from_unit"] == "CLP" and conversion["to_unit"] == "UF"
    assert conversion["reference_date"] == "2026-03-31"


def test_market_unit_value_takes_the_latest_observation_of_the_requested_month():
    rows = run(metric="valor_cuota_serie", funds=("TRI",), period="2026-08",
               dimensions=(("valuation_basis", "market"),)).rows
    assert {row.dimensions["series"]: row.value for row in rows} == {"A": 15000.0, "C": 17000.0, "I": 11000.0}
    assert {row.provenance["fecha"] for row in rows} == {"2026-08-07"}


def test_market_unit_value_of_the_pt_single_series():
    row = one(metric="valor_cuota_serie", funds=("PT",), period="2026-08",
              dimensions=(("valuation_basis", "market"),))
    assert row.value == 14000.0


def test_duplicated_book_snapshot_rows_produce_exactly_one_observation():
    """raw_valor_cuota_contable holds two identical rows for 2025-12; the
    period_point contract must collapse them, never emit the month twice."""
    row = one(metric="valor_cuota_serie", funds=("TRI",), period="2025-12", selector="A",
              dimensions=(("valuation_basis", "book"),))
    assert row.period == "2025-12"


# --------------------------------------------------------------------------
# Distributions
# --------------------------------------------------------------------------

def test_distributions_are_per_unit_events_with_duplicate_source_rows_collapsed():
    rows = run(metric="distribucion_por_cuota_serie", funds=("TRI",), period="2025-01",
               period_end="2025-12", selector="A", dimensions=(("flow_type", "dividend"),)).rows
    assert [row.period for row in rows] == ["2025-04", "2025-07", "2025-10", "2025-12"]
    assert rows[0].value == pytest.approx(0.006581010604083911)
    assert {row.provenance["source_file"] for row in rows} == {"cdg_extract.xlsx"}


def test_distribution_events_can_be_totalled_over_a_year_without_dense_coverage():
    row = one(metric="distribucion_por_cuota_serie", funds=("TRI",), period="2025-01",
              period_end="2025-12", selector="A", dimensions=(("flow_type", "dividend"),),
              aggregation="sum")
    assert row.value == pytest.approx(0.017472203149526574)
    assert row.provenance["temporal_completeness"] == "event"
    assert row.provenance["source_periods"] == ["2025-04", "2025-07", "2025-10", "2025-12"]


def test_capital_reductions_are_a_separate_flow_type_not_mixed_into_dividends():
    reductions = run(metric="distribucion_por_cuota_serie", funds=("Apo",), period="2020-01",
                     period_end="2021-12", dimensions=(("flow_type", "capital_reduction"),)).rows
    assert len(reductions) == 6
    assert {row.provenance["tipo"] for row in reductions} == {"disminucion"}
    none_for_tri = run(metric="distribucion_por_cuota_serie", funds=("TRI",), period="2025-01",
                       period_end="2025-12", selector="A",
                       dimensions=(("flow_type", "capital_reduction"),)).rows
    assert none_for_tri == ()


# --------------------------------------------------------------------------
# Capital, units, equity
# --------------------------------------------------------------------------

def test_subscribed_capital_reports_the_period_it_was_actually_observed_in():
    row = one(metric="capital_suscrito_serie", funds=("TRI",), period="2026-08", selector="A")
    assert row.value == pytest.approx(478440.79974975146)
    # The newest observation is from 2021 -- it must not be relabelled as the
    # requested month, or a stale figure would read as current.
    assert row.period == "2021-09"
    assert row.provenance["temporal_contract"] == "as_of"


def test_units_outstanding_is_reported_per_series():
    rows = run(metric="cuotas_en_circulacion_serie", funds=("TRI",), period="2026-08").rows
    assert {row.dimensions["series"]: row.value for row in rows} == {
        "A": 475667.0, "C": 1252928.0, "I": 1091101.0}
    assert {row.unit for row in rows} == {"cuotas"}


def test_book_equity_per_series_comes_from_the_governed_view():
    row = one(metric="patrimonio_contable_serie", funds=("TRI",), period="2026-03", selector="A")
    assert row.value == pytest.approx(386124.59)
    assert row.unit == "UF"
    assert row.provenance["source"] == "v_serie_patrimonio"


def test_market_equity_is_unavailable_rather_than_zero_when_units_are_missing():
    assert run(metric="patrimonio_bursatil_serie", funds=("TRI",), period="2026-08", selector="A").rows == ()
    row = one(metric="patrimonio_bursatil_serie", funds=("TRI",), period="2026-05", selector="A")
    assert row.value == pytest.approx(201039.42834295306)


# --------------------------------------------------------------------------
# Amortization
# --------------------------------------------------------------------------

def test_consolidated_amortization_totals_the_observed_year():
    row = one(metric="amortizacion_capital_fondo", funds=("TRI",), period="2025-01",
              period_end="2025-12", aggregation="sum")
    assert row.value == pytest.approx(206413.879, abs=0.01)
    assert row.entity_id == "TRI" and row.unit == "UF"


def test_amortization_never_reports_the_future_schedule_tail_as_observed():
    """CONSOLIDADO_TRI carries scheduled rows out to 2072. A window entirely
    beyond the observed debt horizon must yield no observation at all, and a
    naive MAX(periodo) must never surface as the latest amortization."""
    assert run(metric="amortizacion_capital_fondo", funds=("TRI",),
               period="2030-01", period_end="2030-12").rows == ()
    latest = run(metric="amortizacion_capital_fondo", funds=("TRI",),
                 period="2017-01", period_end="2072-12").rows
    assert latest and latest[-1].period <= "2026-06"
    assert {row.dimensions["schedule_basis"] for row in latest} == {"observed"}


def test_per_credit_amortization_is_a_separate_concept_from_the_consolidated_total():
    rows = run(metric="amortizacion_capital_credito", funds=("TRI",), period="2025-01",
               period_end="2025-12", aggregation="sum").rows
    per_credit = {row.entity_id: row.value for row in rows}
    assert per_credit["TRI_CURICO_METLIFE"] == pytest.approx(6852.51, abs=0.01)
    # Deliberately NOT equal to the consolidated figure: the consolidated
    # series includes prepayments/refinancings the per-facility schedules do
    # not, so the two are modelled as different concepts instead of one being
    # silently substituted for the other.
    assert sum(per_credit.values()) != pytest.approx(206413.879, abs=1.0)
