from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "ingesta.html").read_text(encoding="utf-8")


def test_inicio_detalle_no_expone_scroll_horizontal():
    assert ".inicio-expand-body { display: none; margin-top: 10px; overflow-x: auto; }" not in HTML
    assert "overflow-x: hidden" in HTML
    assert "min-width: max-content" not in HTML
    assert "width: 100%" in HTML


def test_navegar_timeline_actualiza_resumen_y_detalle():
    assert "function _inicioTimelineHtml(periodos, frecuencia)" in HTML
    assert "function _inicioDetalleHtml(subIngestas, frecuencia, offsetMin, offset, n)" in HTML
    assert "function _inicioRenderDetalle(card, cache, offset)" in HTML
    assert "timeline.innerHTML = _inicioTimelineHtml(ventana, frecuencia);" in HTML
    assert "_inicioRenderDetalle(card, cache, nuevoOffset);" in HTML


def test_detalle_usa_misma_ventana_y_celdas_regeneradas_siguen_clickables():
    assert "const ventana = sub.periodos.slice(start, start + n);" in HTML
    assert "const headHtml = ventana.map" in HTML
    assert 'data-sub-key="${sub.key}"' in HTML
    assert "container.addEventListener('click', (event) => {" in HTML
    assert "event.target.closest('.inicio-matrix .cell[data-estado=\"miss\"]')" in HTML


def test_detalle_headers_usan_label_compacto_sin_solaparse():
    assert "function _inicioDetallePeriodoLabel(periodo, frecuencia)" in HTML
    assert "const headHtml = ventana.map(t => _inicioDetallePeriodoLabel(t.periodo, frecuencia)).join('');" in HTML

    head_rule = re.search(r"\.inicio-matrix \.head \{(?P<body>.*?)\n  \}", HTML, re.S)
    assert head_rule is not None
    assert "white-space: nowrap" not in head_rule.group("body")
    assert "display: flex" in head_rule.group("body")
    assert "line-height" in head_rule.group("body")
