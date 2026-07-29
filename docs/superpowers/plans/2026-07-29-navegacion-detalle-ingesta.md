# Navegacion Detalle Ingesta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the top timeline arrows in ingestion cards update the expanded detail matrix too, removing the lower horizontal scrollbar while keeping row labels visible.

**Architecture:** Keep each card's `data-offset` as the single navigation state and reuse the existing `/api/estado_ingesta/timeline_range` cache. Extract small vanilla-JS helpers in `web/ingesta.html` so the same period window renders the top timeline and the detail matrix. Add a focused regression test that reads `web/ingesta.html` and guards the CSS/JS contract.

**Tech Stack:** Vanilla HTML/CSS/JS in `web/ingesta.html`; Python `pytest` static regression test; no new frontend dependencies.

## Global Constraints

- Do not modify backend endpoints or database logic; `GET /api/estado_ingesta/timeline_range` already provides the needed `periodos`, `offset_min`, `offset_max`, `n`, and `sub_ingestas`.
- Preserve the existing dirty worktree and stage only files touched for this task.
- Use `python -X utf8` for Python commands on Windows.
- Do not create a new Node/JS test stack for this narrow UI change.
- Expanded detail cells with `data-estado="miss"` must remain clickable after arrow navigation.
- The expanded detail body must not expose a horizontal scrollbar.

---

### Task 1: Synchronized Detail Navigation

**Files:**
- Modify: `web/ingesta.html`
- Test: `tests/test_ingesta_inicio_detalle_ui.py`

**Interfaces:**
- Consumes: `_timelineRangoCache[tipoId]`, where each cache payload has `offset_min: number`, `offset_max: number`, `n: number`, `periodos: Array<{periodo, estado}>`, and optionally `sub_ingestas: Array<{key, label, periodos: Array<{periodo, estado}>}>`.
- Produces: `_inicioTimelineHtml(periodos: Array, frecuencia: string) -> string`.
- Produces: `_inicioDetalleHtml(subIngestas: Array, frecuencia: string, offsetMin: number, offset: number, n: number) -> string`.
- Produces: `_inicioRenderDetalle(card: HTMLElement, cache: object, offset: number) -> void`.

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_ingesta_inicio_detalle_ui.py`:

```python
from __future__ import annotations

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
    assert "data-sub-key=\"${sub.key}\"" in HTML
    assert "container.addEventListener('click', (event) => {" in HTML
    assert "event.target.closest('.inicio-matrix .cell[data-estado=\"miss\"]')" in HTML
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -X utf8 -m pytest tests/test_ingesta_inicio_detalle_ui.py -v
```

Expected: FAIL because `_inicioTimelineHtml`, `_inicioDetalleHtml`, `_inicioRenderDetalle`, and the no-scroll CSS do not exist yet.

- [ ] **Step 3: Update CSS to remove the lower scrollbar and fit the matrix**

In `web/ingesta.html`, replace the current detail CSS:

```css
  .inicio-expand-body { display: none; margin-top: 10px; overflow-x: auto; }
  .inicio-matrix {
    display: grid; grid-template-columns: 62px repeat(var(--cols, 4), minmax(34px, 1fr));
    gap: 4px 6px; font-size: 11px; align-items: center; min-width: max-content;
  }
```

with:

```css
  .inicio-expand-body { display: none; margin-top: 10px; overflow-x: hidden; }
  .inicio-matrix {
    display: grid; grid-template-columns: minmax(62px, 1.05fr) repeat(var(--cols, 4), minmax(0, 1fr));
    gap: 4px 6px; font-size: 11px; align-items: center; min-width: 0; width: 100%;
  }
```

- [ ] **Step 4: Add timeline/detail render helpers**

In `web/ingesta.html`, immediately before `function renderEstadoIngesta(data)`, add:

```javascript
function _inicioTimelineHtml(periodos, frecuencia) {
  return periodos.map(t => `
    <div class="inicio-tl-item" data-periodo="${t.periodo}">
      <div class="inicio-tl-dot ${t.estado}"></div>
      <span class="inicio-tl-label">${_inicioPeriodoLabel(t.periodo, frecuencia)}</span>
    </div>
  `).join('');
}

function _inicioDetalleHtml(subIngestas, frecuencia, offsetMin, offset, n) {
  if (!subIngestas || !subIngestas.length) return '';
  const start = offset - offsetMin;
  const primeraVentana = subIngestas[0].periodos || subIngestas[0].timeline || [];
  const ventanaBase = primeraVentana.slice(start, start + n);
  const headHtml = ventanaBase.map(t =>
    `<div class="head">${_inicioPeriodoLabel(t.periodo, frecuencia)}</div>`
  ).join('');

  const rowsHtml = subIngestas.map(sub => {
    const serie = sub.periodos || sub.timeline || [];
    const ventana = serie.slice(start, start + n);
    const cells = ventana.map(t => `
      <div class="cell" data-estado="${t.estado}" data-periodo="${t.periodo}" data-sub-key="${sub.key}">
        <span class="dot ${t.estado}"></span>
      </div>
    `).join('');
    return `<div class="rowname" title="${sub.label}">${sub.label}</div>${cells}`;
  }).join('');

  return `<div></div>${headHtml}${rowsHtml}`;
}

function _inicioRenderDetalle(card, cache, offset) {
  const matrix = card.querySelector('.inicio-matrix');
  if (!matrix || !cache.sub_ingestas || !cache.sub_ingestas.length) return;
  matrix.style.setProperty('--cols', String(cache.n));
  matrix.innerHTML = _inicioDetalleHtml(
    cache.sub_ingestas,
    card.dataset.frecuencia,
    cache.offset_min,
    offset,
    cache.n
  );
}
```

- [ ] **Step 5: Use helpers during initial render**

Inside `renderEstadoIngesta(data)`, replace the inline timeline HTML:

```javascript
    const timelineHtml = tipo.timeline.map(t => `
      <div class="inicio-tl-item" data-periodo="${t.periodo}">
        <div class="inicio-tl-dot ${t.estado}"></div>
        <span class="inicio-tl-label">${_inicioPeriodoLabel(t.periodo, tipo.frecuencia)}</span>
      </div>
    `).join('');
```

with:

```javascript
    const timelineHtml = _inicioTimelineHtml(tipo.timeline, tipo.frecuencia);
```

Inside the `if (tieneSubs)` block, replace the current `subTimeline`, `cols`, `headHtml`, `rowsHtml` block with:

```javascript
      const subTimeline = tipo.sub_ingestas[0].timeline;
      const cols = subTimeline.length;
      const detalleHtml = _inicioDetalleHtml(tipo.sub_ingestas, tipo.frecuencia, 0, 0, cols);
```

Then replace:

```html
            <div></div>${headHtml}
            ${rowsHtml}
```

with:

```html
            ${detalleHtml}
```

- [ ] **Step 6: Use event delegation so regenerated miss cells remain clickable**

Inside `renderEstadoIngesta(data)`, remove this direct listener block:

```javascript
  container.querySelectorAll('.inicio-matrix .cell[data-estado="miss"]').forEach(cell => {
    cell.addEventListener('click', () => {
      const card = cell.closest('.inicio-card');
      const tabDestino = card.querySelector('button[data-tab-destino]').dataset.tabDestino;
      _irAIngestar(tabDestino, cell.dataset.periodo, cell.dataset.subKey);
    });
  });
```

Replace it with one delegated listener guarded by a dataset flag:

```javascript
  if (!container.dataset.detalleClickBound) {
    container.addEventListener('click', (event) => {
      const cell = event.target.closest('.inicio-matrix .cell[data-estado="miss"]');
      if (!cell || !container.contains(cell)) return;
      const card = cell.closest('.inicio-card');
      const tabDestino = card.querySelector('button[data-tab-destino]').dataset.tabDestino;
      _irAIngestar(tabDestino, cell.dataset.periodo, cell.dataset.subKey);
    });
    container.dataset.detalleClickBound = '1';
  }
```

- [ ] **Step 7: Update `navegarTimeline` to re-render both levels**

Inside `navegarTimeline(card, delta)`, keep the existing offset bounds and `ventana` slicing. Replace the inline timeline rendering:

```javascript
  timeline.innerHTML = ventana.map(t => `
    <div class="inicio-tl-item" data-periodo="${t.periodo}">
      <div class="inicio-tl-dot ${t.estado}"></div>
      <span class="inicio-tl-label">${_inicioPeriodoLabel(t.periodo, frecuencia)}</span>
    </div>
  `).join('');
```

with:

```javascript
  timeline.innerHTML = _inicioTimelineHtml(ventana, frecuencia);
  _inicioRenderDetalle(card, cache, nuevoOffset);
```

- [ ] **Step 8: Run focused regression tests**

Run:

```powershell
python -X utf8 -m pytest tests/test_ingesta_inicio_detalle_ui.py tests/db/test_estado_ingesta.py -v
```

Expected: PASS.

- [ ] **Step 9: Run the server test for the affected endpoint**

Run:

```powershell
python -X utf8 -m pytest tests/test_ingesta_server_estado.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add web/ingesta.html tests/test_ingesta_inicio_detalle_ui.py
git commit -m "feat(ingesta): sincroniza detalle con timeline superior"
```
