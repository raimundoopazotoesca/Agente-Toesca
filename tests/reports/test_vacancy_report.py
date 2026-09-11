from pathlib import Path

from tools.reports.vacancy import VacancyReportContext, VacancyReportProvider


DB = Path("memory/agente_toesca_v2.db")


def test_provider_returns_versioned_observed_apo_report():
    report = VacancyReportProvider(DB).build(VacancyReportContext(fund="Apo", period="2026-06"))

    assert report["schema_version"] == "vacancy_report_v1"
    assert report["context"]["fund"] == "Apo"
    assert report["context"]["period"] == "2026-06"
    assert report["summary"]["status"] in {"available", "partial"}
    assert report["history"]["rows"]
    assert report["coverage"]["observed_through"] == "2026-06"


def test_provider_keeps_requested_future_period_visible_without_creating_a_snapshot():
    report = VacancyReportProvider(DB).build(VacancyReportContext(fund="Apo", period="2026-08"))

    assert report["context"]["requested_period"] == "2026-08"
    assert report["context"]["period"] == "2026-06"
    assert report["coverage"]["requested_period_available"] is False
    assert report["coverage"]["reason_code"] == "period_not_observed"
    assert all(row["period"] <= "2026-06" for row in report["history"]["rows"])


def test_provider_marks_including_parking_as_an_explicit_alternate_scope():
    canonical = VacancyReportProvider(DB).build(VacancyReportContext(fund="PT", period="2026-06"))
    alternate = VacancyReportProvider(DB).build(
        VacancyReportContext(fund="PT", period="2026-06", parking_scope="include")
    )

    assert canonical["context"]["parking_scope"] == "exclude"
    assert alternate["context"]["parking_scope"] == "include"
    assert alternate["summary"]["metrics"][0]["metric_id"] == "vacancia_fisica_pct_incluye_estacionamientos"
    assert alternate["summary"]["metrics"][0]["value"] != canonical["summary"]["metrics"][0]["value"]


def test_provider_returns_a_portfolio_asset_radar_without_machali():
    report = VacancyReportProvider(DB).build(VacancyReportContext(fund="Apo", period="2026-06"))

    rows = report["asset_overview"]["rows"]
    assert rows
    assert {"asset_key", "label", "fund", "period", "vacancy_pct", "spatial_status"} <= set(rows[0])
    assert "Strip Machalí" not in {row["asset_key"] for row in rows}
    assert {"Apo4501", "Apo4700", "Apo3001", "Torre A"} <= {row["asset_key"] for row in rows}


def test_provider_returns_persisted_floor_layout_for_selected_asset():
    report = VacancyReportProvider(DB).build(
        VacancyReportContext(fund="Apo", period="2026-06", asset="Apo4501")
    )

    spatial = report["spatial_occupancy"]
    assert spatial["status"] == "available"
    assert spatial["buildings"]
    assert {"building", "floors"} <= set(spatial["buildings"][0])
    assert {"floor", "vacancy_pct", "vacant_m2"} <= set(spatial["buildings"][0]["floors"][0])
