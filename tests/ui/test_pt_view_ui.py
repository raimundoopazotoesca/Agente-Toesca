from pathlib import Path


def test_pt_shell_prioritizes_the_two_building_cards():
    html = Path("web/pt.html").read_text(encoding="utf-8")

    for region in ("pt-context", "building-cards"):
        assert f'id="{region}"' in html
    assert 'src="/pt.js"' in html
    assert "building-card" in html


def test_pt_shell_includes_consolidated_insights_charts():
    html = Path("web/pt.html").read_text(encoding="utf-8")

    assert 'id="pt-insights"' in html
    for chart_id in ("chart-rubro", "chart-tipo", "chart-vencimiento", "chart-vacancia"):
        assert f'id="{chart_id}"' in html
