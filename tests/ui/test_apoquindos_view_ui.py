from pathlib import Path


def test_apoquindos_shell_prioritizes_the_two_building_layouts():
    html = Path("web/apoquindos.html").read_text(encoding="utf-8")

    for region in ("apo-context", "building-layouts", "apo-history"):
        assert f'id="{region}"' in html
    assert 'src="/apoquindos.js"' in html
    assert "building-shape" in html
    assert "local-layout" in html


def test_apoquindos_shell_includes_consolidated_insights_charts():
    html = Path("web/apoquindos.html").read_text(encoding="utf-8")

    assert 'id="apo-insights"' in html
    for chart_id in ("chart-rubro", "chart-tipo", "chart-vencimiento", "chart-vacancia"):
        assert f'id="{chart_id}"' in html
