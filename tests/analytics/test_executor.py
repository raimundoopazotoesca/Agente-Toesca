from pathlib import Path

import pytest

from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError


DB = Path("memory/agente_toesca_v2.db")


def test_canonical_fund_lookup_returns_semantic_row():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06"))
    assert result.catalog_version == 1
    assert result.rows[0].value == 5.945
    assert result.rows[0].source_kind == "canonical"
    assert result.rows[0].provenance["ingest_run_id"] == 142


def test_breakdown_ranks_tri_assets_by_vacant_area():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("m2_vacantes", funds=("TRI",), period="2026-06", group_by="asset", order_by="value_desc"))
    values = {row.entity_id: row.value for row in result.rows}
    assert result.rows[0].entity_id == "Mall Curicó"
    assert values["Apo3001"] == pytest.approx(1632.6)
    assert values["Viña Centro"] == pytest.approx(199.83)


def test_physical_asset_vacancy_uses_governed_view_value():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_fisica_pct_activo", assets=("Apo3001",), period="2026-06"))
    assert result.rows[0].value == pytest.approx(0.3620316883)
    assert result.rows[0].source_kind == "breakdown"


def test_fund_vacancy_falls_back_to_rollup_view_when_no_derived_kpi_row():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Apo",), period="2026-06"))
    assert result.rows[0].entity_id == "Apo"
    assert result.rows[0].value == pytest.approx(11.487640062391586, abs=1e-6)
    assert result.rows[0].provenance["ingest_run_id"] is None
    assert result.rows[0].provenance["formula"].startswith("rollup_ratio:v_vacancia_activo:[Apo4501,Apo4700]:")


def test_fund_vacancy_rollup_uses_ratio_of_sums_not_average_of_per_asset_percentages():
    import sqlite3
    connection = sqlite3.connect("file:memory/agente_toesca_v2.db?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT m2_gla, m2_vacantes FROM v_vacancia_activo WHERE activo_key IN ('Apo4501','Apo4700') AND periodo='2026-06'"
    ).fetchall()
    non_null = [row for row in rows if row[0] is not None and row[1] is not None]
    expected = sum(row[1] for row in non_null) * 100.0 / sum(row[0] for row in non_null)

    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Apo",), period="2026-06"))
    assert result.rows[0].value == pytest.approx(expected)
    # a naive average of the two assets' own percentages would give a different number
    per_asset_avg = sum(row[1] / row[0] for row in non_null) * 100.0 / len(non_null)
    assert result.rows[0].value != pytest.approx(per_asset_avg)


def test_fund_vacancy_rollup_covers_the_full_governed_series_with_no_gaps():
    # the manual-era fund-level source (pre rent-roll) and the rent-roll-era
    # per-asset source must both resolve, with no month silently missing.
    executor = AnalyticsExecutor(DB)
    for period in ("2019-10", "2019-11", "2025-06", "2025-12", "2026-01", "2026-06"):
        result = executor.execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Apo",), period=period))
        assert len(result.rows) == 1, f"expected a value for {period}"
        assert result.rows[0].value is not None


def test_fund_vacancy_rollup_before_first_covered_period_is_none_not_zero():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Apo",), period="2018-01"))
    assert result.rows == ()


def test_fund_vacancy_without_derived_kpi_or_rollup_mapping_returns_none():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Ren",), period="2026-06"))
    assert result.rows == ()


def test_fund_vacancy_prefers_materialized_derived_kpi_over_rollup_for_tri():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06"))
    assert result.rows[0].provenance["ingest_run_id"] == 142
    assert not result.rows[0].provenance["formula"].startswith("rollup_ratio:")


def test_fund_vacancy_rollup_prefers_granular_asset_group_over_fund_total_group():
    # 2026-06 has both the granular Apo4501+Apo4700 rent-roll rows AND a
    # synthetic 'Fondo Apoquindo' manual total row; the more granular,
    # higher-priority group must win deterministically.
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Apo",), period="2026-06"))
    assert "[Apo4501,Apo4700]" in result.rows[0].provenance["formula"]


@pytest.mark.parametrize("query", [
    AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06", group_by="asset"),
    AnalyticsQueryRequest("unknown", funds=("TRI",), period="2026-06"),
    AnalyticsQueryRequest("m2_vacantes", funds=("TRI",), period="2026-06", group_by="unknown"),
    AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06", aggregation="sum"),
])
def test_invalid_semantic_requests_fail_closed(query):
    with pytest.raises(SemanticQueryError):
        AnalyticsExecutor(DB).execute(query)
