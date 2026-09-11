from pathlib import Path


def test_report_shell_has_context_summary_history_and_coverage_regions():
    html = Path("web/vacancy_report.html").read_text(encoding="utf-8")

    for region in ("report-context", "report-summary", "report-history", "report-coverage"):
        assert f'id="{region}"' in html


def test_report_shell_loads_its_contract_only_renderer():
    html = Path("web/vacancy_report.html").read_text(encoding="utf-8")

    assert 'src="/vacancy_report.js"' in html


def test_report_shell_has_asset_radar_and_spatial_occupancy_regions():
    html = Path("web/vacancy_report.html").read_text(encoding="utf-8")

    for region in ("asset-radar", "spatial-occupancy"):
        assert f'id="{region}"' in html
