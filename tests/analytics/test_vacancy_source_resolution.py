"""Frozen, fixture-only holdout for the generic fallback/rollup source
resolution mechanism behind vacancia_pct_fondo. Entities here are synthetic
(fund-1/fund-2/fund-3, asset-a/asset-b/...) — no production Apo/PT/TRI keys
or values appear in this file, so these cases cannot be satisfied by
anything tuned specifically to Apoquindo."""
from pathlib import Path
import sqlite3

import pytest

from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest


CATALOG = """catalog_version: 1
metrics:
- key: vacancy_holdout
  display_name: Vacancy holdout fixture
  description: fixture
  unit: pct_0_100
  entity_grain: fund
  period_grain: month
  source_kind: canonical
  access:
    kind: fallback_chain
    primary: {kind: derived_kpi, entity_type: fondo, kpi: vacancia_pct}
    fallback:
      kind: rollup_ratio_view
      view: v_component
      entity_column: entity_key
      asset_groups:
        fund-1: [[asset-a], [fund-1-total]]
        fund-2: [[asset-b, asset-c], [fund-2-total]]
      numerator_column: m2_vacantes
      denominator_column: m2_gla
  aggregation: non_additive
  allowed_dimensions: [fund, period]
  status: active
  related_metrics: []
  methodology: fixture_v1
  nature: ratio
  allowed_temporal_aggregations: []
"""


@pytest.fixture
def executor(tmp_path: Path) -> AnalyticsExecutor:
    db_path = tmp_path / "holdout.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE derived_kpi (entidad_tipo TEXT, entidad_key TEXT, kpi TEXT, periodo TEXT, valor REAL, formula TEXT, ingest_run_id INTEGER)"
    )
    # fund-1 has a materialized canonical row for 2026-01 (source A: stored canonical value).
    connection.execute(
        "INSERT INTO derived_kpi VALUES ('fondo','fund-1','vacancia_pct','2026-01', 42.0, 'stored_canonical', 900)"
    )
    connection.execute("CREATE TABLE v_component (entity_key TEXT, periodo TEXT, m2_gla REAL, m2_vacantes REAL)")
    connection.executemany(
        "INSERT INTO v_component VALUES (?,?,?,?)",
        [
            # fund-1 also has a granular-asset row for the SAME period as its stored row —
            # a deliberate conflicting-equivalent-source case: primary must still win.
            ("asset-a", "2026-01", 100.0, 50.0),
            # fund-1, a later period: no derived_kpi row, but the granular group (asset-a)
            # has a valid component pair — must be used over the lower-priority total group.
            ("asset-a", "2026-03", 40.0, 10.0),
            ("fund-1-total", "2026-03", 999.0, 999.0),
            # fund-1, an even later period: the granular group has gone silent (represents
            # a source-representation change over time, e.g. rent-roll era ending); only
            # the fund-level total group has data -> must fall back to it.
            ("fund-1-total", "2026-04", 200.0, 60.0),
            # fund-2: no derived_kpi row anywhere -> must be derived from summing its
            # granular component group (source B: ratio of sums).
            ("asset-b", "2026-02", 80.0, 20.0),
            ("asset-c", "2026-02", 20.0, 0.0),
        ],
    )
    connection.commit()
    connection.close()
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(CATALOG, encoding="utf-8")
    return AnalyticsExecutor(db_path, catalog_path)


def _query(executor, fund, period):
    return executor.execute(AnalyticsQueryRequest("vacancy_holdout", funds=(fund,), period=period))


def test_a_stored_canonical_source_wins_even_with_a_conflicting_equivalent_source(executor):
    result = _query(executor, "fund-1", "2026-01")
    assert len(result.rows) == 1
    assert result.rows[0].value == 42.0
    assert result.rows[0].provenance["formula"] == "stored_canonical"
    assert result.rows[0].provenance["ingest_run_id"] == 900


def test_b_derived_from_components_computes_ratio_of_sums(executor):
    result = _query(executor, "fund-2", "2026-02")
    assert len(result.rows) == 1
    # ratio of sums: (20+0) / (80+20) * 100, NOT average of per-component percentages
    assert result.rows[0].value == pytest.approx(20.0)


def test_c_ratio_of_sums_not_average_of_percentages(executor):
    # per-component percentages are 25% (asset-b) and 0% (asset-c); a naive
    # average would give 12.5%, but the correct weighted ratio-of-sums is 20%.
    result = _query(executor, "fund-2", "2026-02")
    assert result.rows[0].value != pytest.approx(12.5)
    assert result.rows[0].value == pytest.approx(20.0)


def test_d_missing_observation_returns_none_not_zero(executor):
    result = _query(executor, "fund-2", "2026-01")
    assert result.rows == ()


def test_e_multiple_periods_each_remain_point_in_time(executor):
    result = executor.execute(AnalyticsQueryRequest("vacancy_holdout", funds=("fund-1",), period="2026-01", period_end="2026-02"))
    assert len(result.rows) == 1
    assert result.rows[0].period == "2026-01"


def test_f_group_precedence_switches_over_time_without_fund_specific_code(executor):
    # 2026-03: granular group has data -> wins over the total group even though
    # both exist for that period.
    granular = _query(executor, "fund-1", "2026-03")
    assert granular.rows[0].value == pytest.approx(25.0)  # 10/40*100
    assert "[asset-a]" in granular.rows[0].provenance["formula"]

    # 2026-04: granular group has gone silent -> deterministically falls back
    # to the fund-level total group, purely from data (group order), no branching.
    total = _query(executor, "fund-1", "2026-04")
    assert total.rows[0].value == pytest.approx(30.0)  # 60/200*100
    assert "[fund-1-total]" in total.rows[0].provenance["formula"]


def test_g_no_compatible_source_returns_none(executor):
    result = _query(executor, "fund-3", "2026-01")
    assert result.rows == ()


def test_h_lineage_identifies_source_and_components_for_derived_result(executor):
    result = _query(executor, "fund-2", "2026-02")
    formula = result.rows[0].provenance["formula"]
    assert formula.startswith("rollup_ratio:v_component:[asset-b,asset-c]:")
    assert "m2_vacantes" in formula and "m2_gla" in formula
