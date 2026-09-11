from pathlib import Path

import pytest

from scripts.build_factsheet import _fetch_perf_data, _fetch_vacancia_tri
from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest
from tools.db.connection import get_conn
from tools.reports.vacancy import VacancyReportContext, VacancyReportProvider


DB = Path("memory/agente_toesca_v2.db")


def _report_row(fund: str, period: str) -> dict:
    report = VacancyReportProvider(DB).build(VacancyReportContext(fund=fund, period=period, window="historico"))
    return next(row for row in report["history"]["rows"] if row["period"] == period)


@pytest.mark.parametrize("fund", ["PT", "Apo"])
def test_canonical_excluded_parking_scope_matches_the_governed_metric_contract(fund: str):
    period = "2026-06"
    report = _report_row(fund, period)
    governed = AnalyticsExecutor(DB).execute(
        AnalyticsQueryRequest(metric="vacancia_pct_fondo", funds=(fund,), period=period)
    ).rows[0]

    assert report["vacancy_pct"] == pytest.approx(governed.value)


@pytest.mark.parametrize("fund", ["PT", "Apo"])
def test_factsheet_performance_total_remains_a_distinct_including_parking_surface(fund: str):
    period = "2026-06"
    factsheet = _fetch_perf_data(fund)[period]["__grand_total__|||Total"]
    report = _report_row(fund, period)

    assert report["gla_m2"] != pytest.approx(factsheet["m2_utiles"])


def test_tri_history_matches_the_validated_factsheet_hybrid_series():
    period = "2026-06"

    assert _report_row("TRI", period)["vacancy_pct"] == _fetch_vacancia_tri(get_conn())[period]
