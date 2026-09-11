from pathlib import Path

import pytest


@pytest.mark.parametrize("page,script", [
    ("vina", "single_asset_report.js"),
    ("curico", "single_asset_report.js"),
    ("sucden", "simple_asset_report.js"),
    ("inmosa", "simple_asset_report.js"),
])
def test_single_asset_shell_has_required_regions_and_switcher(page, script):
    html = Path(f"web/{page}.html").read_text(encoding="utf-8")

    assert 'id="building-cards"' in html
    assert 'id="coverage"' in html
    assert f'src="/{script}"' in html
    assert "asset-switcher" in html
    # Cada activo debe poder llegar a los otros 5.
    for other in ("apoquindos", "pt", "vina", "curico", "sucden", "inmosa"):
        assert f'href="/reports/{other}"' in html


def test_vina_and_curico_shells_include_consolidated_insights_charts():
    for page in ("vina", "curico"):
        html = Path(f"web/{page}.html").read_text(encoding="utf-8")
        assert 'id="asset-insights"' in html
        for chart_id in ("chart-rubro", "chart-tipo", "chart-vencimiento", "chart-vacancia"):
            assert f'id="{chart_id}"' in html


def test_sucden_and_inmosa_shells_skip_composition_charts():
    for page in ("sucden", "inmosa"):
        html = Path(f"web/{page}.html").read_text(encoding="utf-8")
        assert "chart-rubro" not in html
