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
    assert result.rows[0].provenance["formula"].startswith("rollup_ratio:v_vacancia_apoquindo_consolidado_tipo:")


def test_fund_vacancy_rollup_excludes_parking_and_uses_ratio_of_sums_not_average():
    import sqlite3
    connection = sqlite3.connect("file:memory/agente_toesca_v2.db?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT tipo_unidad, m2_gla, m2_vacantes FROM v_vacancia_apoquindo_consolidado_tipo WHERE periodo='2026-06'"
    ).fetchall()
    non_parking = [row for row in rows if row[0] != "Estacionamiento" and row[1] is not None and row[2] is not None]
    expected = sum(row[2] for row in non_parking) * 100.0 / sum(row[1] for row in non_parking)

    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Apo",), period="2026-06"))
    assert result.rows[0].value == pytest.approx(expected)


def test_fund_vacancy_rollup_returns_none_outside_source_coverage_not_zero():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Apo",), period="2018-01"))
    assert result.rows == ()


def test_fund_vacancy_without_derived_kpi_or_rollup_mapping_returns_none():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("Ren",), period="2026-06"))
    assert result.rows == ()


def test_fund_vacancy_prefers_materialized_derived_kpi_over_rollup_for_tri():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06"))
    assert result.rows[0].provenance["ingest_run_id"] == 142
    assert not result.rows[0].provenance["formula"].startswith("rollup_ratio:")


@pytest.mark.parametrize("query", [
    AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06", group_by="asset"),
    AnalyticsQueryRequest("unknown", funds=("TRI",), period="2026-06"),
    AnalyticsQueryRequest("m2_vacantes", funds=("TRI",), period="2026-06", group_by="unknown"),
    AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06", aggregation="sum"),
])
def test_invalid_semantic_requests_fail_closed(query):
    with pytest.raises(SemanticQueryError):
        AnalyticsExecutor(DB).execute(query)
