"""Frozen, fixture-only holdout for the generic fallback/rollup source
resolution mechanism behind vacancia_pct_fondo. Entities here are synthetic
(fund-1/fund-2/fund-3) — no production Apo/PT/TRI keys or values appear in
this file, so these cases cannot be satisfied by anything tuned specifically
to Apoquindo."""
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
      views: {fund-2: v_rollup_2, fund-1: v_rollup_1}
      numerator_column: vac
      denominator_column: gla
      exclude_column: tipo
      exclude_value: parking
      dedupe_columns: [tipo]
      precedence_column: fuente
      precedence_order: [primary_src, backup_src]
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
    connection.execute("CREATE TABLE v_rollup_1 (periodo TEXT, tipo TEXT, gla REAL, vac REAL, fuente TEXT)")
    connection.execute("CREATE TABLE v_rollup_2 (periodo TEXT, tipo TEXT, gla REAL, vac REAL, fuente TEXT)")
    connection.executemany(
        "INSERT INTO v_rollup_1 VALUES (?,?,?,?,?)",
        [
            # fund-1 also has rollup component data for the SAME period as its stored row —
            # a deliberate conflicting-equivalent-source case: primary must still win.
            ("2026-01", "office", 100.0, 50.0, "primary_src"),
        ],
    )
    connection.executemany(
        "INSERT INTO v_rollup_2 VALUES (?,?,?,?,?)",
        [
            # fund-2: no derived_kpi row anywhere -> must be derived from components (source B).
            ("2026-02", "office", 80.0, 20.0, "primary_src"),
            ("2026-02", "retail", 20.0, 0.0, "primary_src"),
            ("2026-02", "parking", 999.0, 999.0, "primary_src"),  # excluded dimension value
            # duplicate/near-duplicate backup-source rows for the same (period, tipo) — must be
            # deduped by precedence (primary_src wins), not summed twice.
            ("2026-02", "office", 80.0, 20.0, "backup_src"),
            ("2026-02", "retail", 20.0, 0.0, "backup_src"),
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
    # ratio of sums: (20+0) / (80+20) * 100, NOT average of per-type percentages
    assert result.rows[0].value == pytest.approx(20.0)


def test_c_ratio_of_sums_not_average_of_percentages(executor):
    # per-type percentages are 25% (office) and 0% (retail); a naive average
    # would give 12.5%, but the correct weighted ratio-of-sums is 20%.
    result = _query(executor, "fund-2", "2026-02")
    assert result.rows[0].value != pytest.approx(12.5)
    assert result.rows[0].value == pytest.approx(20.0)


def test_c2_excluded_dimension_and_backup_duplicates_do_not_skew_the_ratio(executor):
    result = _query(executor, "fund-2", "2026-02")
    # if parking or the duplicate backup_src rows leaked in, the value would differ from 20.0
    assert result.rows[0].value == pytest.approx(20.0)


def test_d_missing_observation_returns_none_not_zero(executor):
    result = _query(executor, "fund-2", "2026-01")
    assert result.rows == ()


def test_e_multiple_periods_each_remain_point_in_time(executor):
    result = executor.execute(AnalyticsQueryRequest("vacancy_holdout", funds=("fund-1",), period="2026-01", period_end="2026-02"))
    assert len(result.rows) == 1
    assert result.rows[0].period == "2026-01"


def test_g_no_compatible_source_returns_none(executor):
    result = _query(executor, "fund-3", "2026-01")
    assert result.rows == ()


def test_h_lineage_identifies_source_and_components_for_derived_result(executor):
    result = _query(executor, "fund-2", "2026-02")
    formula = result.rows[0].provenance["formula"]
    assert formula.startswith("rollup_ratio:v_rollup_2:")
    assert "vac" in formula and "gla" in formula
