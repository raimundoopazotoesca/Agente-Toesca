from pathlib import Path
import sqlite3

import pytest

from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest, SemanticQueryError


DB = Path("memory/agente_toesca_v2.db")


def _fixture_executor(tmp_path: Path, key: str, nature: str, aggregations: str) -> AnalyticsExecutor:
    db_path = tmp_path / "semantic.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE derived_kpi (entidad_tipo TEXT, entidad_key TEXT, kpi TEXT, periodo TEXT, valor REAL, formula TEXT, ingest_run_id INTEGER)")
    connection.executemany("INSERT INTO derived_kpi VALUES ('fondo', 'fund-a', ?, ?, ?, 'fixture_v1', 7)", [
        (key, "2026-01", 10), (key, "2026-02", 20), (key, "2026-03", 30),
    ])
    connection.commit()
    connection.close()
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(f"""catalog_version: 1
metrics:
- key: {key}
  display_name: Fixture
  description: fixture
  unit: UF
  entity_grain: fund
  period_grain: month
  source_kind: canonical
  access: {{kind: derived_kpi, entity_type: fondo, kpi: {key}}}
  aggregation: non_additive
  allowed_dimensions: [fund, period]
  status: active
  related_metrics: []
  methodology: fixture_v1
  nature: {nature}
  allowed_temporal_aggregations: {aggregations}
""", encoding="utf-8")
    return AnalyticsExecutor(db_path, catalog)


def test_flow_aggregates_a_fund_range_from_its_canonical_source():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest(
        metric="noi_mensual_fondo", funds=("PT",), period="2025-01", period_end="2025-12", aggregation="sum",
    ))

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.entity_id == "PT"
    assert row.period == "2025-01..2025-12"
    assert row.value == pytest.approx(172868.06, abs=0.01)
    assert row.provenance["source_period_count"] == 12


def test_ratio_rejects_sum_from_contract_not_metric_name():
    with pytest.raises(SemanticQueryError, match="aggregation"):
        AnalyticsExecutor(DB).execute(AnalyticsQueryRequest(
            metric="ltv_fondo", funds=("TRI",), period="2026-04", period_end="2026-06", aggregation="sum",
        ))


def test_synthetic_flow_works_without_executor_metric_branch(tmp_path: Path):
    result = _fixture_executor(tmp_path, "synthetic_flow", "flow", "[sum]").execute(AnalyticsQueryRequest(
        metric="synthetic_flow", funds=("fund-a",), period="2026-01", period_end="2026-03", aggregation="sum",
    ))

    assert result.rows[0].value == 60


def test_synthetic_point_in_time_rejects_sum_from_its_contract(tmp_path: Path):
    with pytest.raises(SemanticQueryError, match="aggregation"):
        _fixture_executor(tmp_path, "synthetic_stock", "point_in_time", "[]").execute(AnalyticsQueryRequest(
            metric="synthetic_stock", funds=("fund-a",), period="2026-01", period_end="2026-03", aggregation="sum",
        ))


def test_fourth_real_metric_requires_only_metadata_for_aggregation():
    result = AnalyticsExecutor(DB).execute(AnalyticsQueryRequest(
        metric="ingresos_mensual_fondo", funds=("PT",), period="2025-01", period_end="2025-03", aggregation="sum",
    ))

    assert result.rows[0].metric_key == "ingresos_mensual_fondo"
    assert result.rows[0].provenance["source_period_count"] == 3
