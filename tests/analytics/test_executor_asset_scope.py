"""Asset-grain derived_kpi access: lookup, breakdown, subset, period range."""
from pathlib import Path

import pytest

from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError

DB = Path("memory/agente_toesca_v2.db")


def _rows(**kwargs):
    return AnalyticsExecutor(DB).execute(AnalyticsQueryRequest(**kwargs))


def test_fund_lookup_path_is_unchanged():
    result = _rows(metric="ltv_fondo", funds=("TRI",), period="2026-06")
    assert result.result_kind == "scalar"
    assert len(result.rows) == 1
    row = result.rows[0]
    assert (row.entity_id, row.entity_type, row.period, row.unit) == ("TRI", "fund", "2026-06", "ratio_0_1")
    assert row.value == pytest.approx(0.6101647, rel=1e-6)


def test_fund_grain_metric_still_rejects_asset_scope_and_grouping():
    with pytest.raises(SemanticQueryError):
        _rows(metric="ltv_fondo", funds=("TRI",), assets=("Apo3001",), period="2026-06")


def test_asset_lookup_returns_canonical_asset_value():
    result = _rows(metric="ltv_activo", assets=("Apo3001",), period="2026-06")
    assert result.result_kind == "scalar"
    assert len(result.rows) == 1
    row = result.rows[0]
    assert (row.entity_id, row.entity_type) == ("Apo3001", "asset")
    assert row.value == pytest.approx(0.7115159, rel=1e-6)


def test_asset_lookup_over_a_period_range_returns_one_row_per_month():
    result = _rows(metric="ltv_activo", assets=("Apo3001",), period="2026-04", period_end="2026-06")
    assert result.result_kind == "scalar"
    assert [row.period for row in result.rows] == ["2026-04", "2026-05", "2026-06"]
    assert len({row.entity_id for row in result.rows}) == 1


def test_asset_breakdown_over_a_fund_joins_dim_activo():
    result = _rows(metric="noi_mensual_activo", funds=("TRI",), period="2026-06",
                   group_by="asset", order_by="value_desc")
    assert result.result_kind == "breakdown"
    entities = [row.entity_id for row in result.rows]
    assert entities == ["Viña Centro", "INMOSA", "Sucden", "Mall Curicó"]
    # 'PT' exists in derived_kpi with entidad_tipo='activo' but is not a TRI
    # asset; the dim_activo join must exclude it.
    assert "PT" not in entities


def test_asset_breakdown_with_explicit_subset_returns_only_the_subset():
    result = _rows(metric="noi_mensual_activo", funds=("TRI",),
                   assets=("INMOSA", "Viña Centro", "Mall Curicó"),
                   period="2026-06", group_by="asset", order_by="value_desc")
    assert [row.entity_id for row in result.rows] == ["Viña Centro", "INMOSA", "Mall Curicó"]
    assert [round(row.value, 2) for row in result.rows] == [10465.96, 7217.0, 979.11]


def test_asset_breakdown_respects_limit_and_ascending_order():
    result = _rows(metric="noi_mensual_activo", funds=("TRI",), period="2026-06",
                   group_by="asset", order_by="value_asc", limit=2)
    assert [row.entity_id for row in result.rows] == ["Mall Curicó", "Sucden"]


def test_asset_metric_requires_some_scope():
    with pytest.raises(SemanticQueryError):
        _rows(metric="ltv_activo", period="2026-06")


def test_asset_metric_rejects_more_than_one_fund_scope():
    with pytest.raises(SemanticQueryError):
        _rows(metric="ltv_activo", funds=("TRI", "PT"), period="2026-06", group_by="asset")
