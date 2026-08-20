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


@pytest.mark.parametrize("query", [
    AnalyticsQueryRequest("vacancia_pct_fondo", funds=("TRI",), period="2026-06", group_by="asset"),
    AnalyticsQueryRequest("unknown", funds=("TRI",), period="2026-06"),
    AnalyticsQueryRequest("m2_vacantes", funds=("TRI",), period="2026-06", group_by="unknown"),
    AnalyticsQueryRequest("m2_vacantes", funds=("TRI",), period="2026-06", aggregation="sum"),
])
def test_invalid_semantic_requests_fail_closed(query):
    with pytest.raises(SemanticQueryError):
        AnalyticsExecutor(DB).execute(query)
