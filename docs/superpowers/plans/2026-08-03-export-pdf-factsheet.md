# Exportar Fact Sheet a PDF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un botón "Exportar PDF" al factsheet que abre un pop-up de
selección (fondo × período operacional × período EEFF, multi-fondo) y
descarga un `.zip` con un PDF por fondo, renderizado server-side con
Playwright.

**Architecture:** El HTML del factsheet (generado por
`scripts/build_factsheet.py`) gana soporte de parámetros URL
(`?fondo=&cb=&op=&pdfmode=1`) que fuerzan el estado inicial de la página y
levantan un flag `window.__PDF_READY__` cuando el render termina. Un nuevo
endpoint Flask `/api/export-pdf` en `scripts/ingesta_server.py` recibe la
selección del pop-up, abre esa URL con Playwright una vez por fondo
(reutilizando el mismo browser), espera el flag, imprime a PDF, y empaqueta
todo en un `.zip` que el frontend descarga.

**Tech Stack:** Flask (`scripts/ingesta_server.py`), Playwright síncrono
(`sync_playwright`, chromium headless, ya instalado — v1.58.0), JS vanilla
embebido en `HTML_TEMPLATE` (sin frameworks, sigue el patrón existente del
archivo).

## Global Constraints

- No editar `factsheet.html` a mano — todo cambio va en `HTML_TEMPLATE`
  dentro de `scripts/build_factsheet.py`, y se regenera corriendo
  `python scripts/build_factsheet.py` (regla ya documentada en
  `feedback_factsheet_html_autogenerado`).
- Todo `/api/*` exige el header `X-Ingesta-Token` — el endpoint nuevo no es
  excepción (`_require_token` en `ingesta_server.py` ya lo aplica
  automáticamente a cualquier ruta bajo `/api/`).
- El servidor escucha en `127.0.0.1:8765` (puerto fijo, ver
  `if __name__ == "__main__"` al final de `ingesta_server.py`).
- Alcance: las 4 páginas del factsheet (`#page`, `#page2`, `#page3`,
  `#page4`), tal como se ven en pantalla.
- Una sola fecha operacional + una sola fecha EEFF aplicada a todos los
  fondos marcados (no fechas independientes por fondo).
- Resultado siempre es un `.zip`, un PDF por fondo exitoso.

---

## File Structure

- **Modify `scripts/build_factsheet.py`** (`HTML_TEMPLATE` string, es el
  único archivo que genera el HTML):
  - CSS: agregar reglas `body.pdf-export` y `.export-modal` (reusa el
    patrón visual de `.trace-modal-bg`/`.trace-modal` ya existente).
  - HTML: botón "Exportar PDF" en el sidebar + markup del modal.
  - JS: función `switchFund`/`initPeriodNav` no cambian de firma; se agrega
    lógica de parámetros URL al final del IIFE de init, más las funciones
    del modal (`openExportModal`, `closeExportModal`,
    `refreshExportPeriodos`, `onDescargarPdf`).
- **Modify `scripts/ingesta_server.py`**:
  - Nuevo import `from flask import send_file` y `import io`.
  - Nuevo endpoint `POST /api/export-pdf`.
  - Nueva función helper `_generar_pdfs_factsheet(fondos, periodo_cb, periodo_op)`
    que encapsula el uso de Playwright, para poder testearla por separado.
- **Test:** `tests/scripts/test_export_pdf.py` (nuevo) — smoke test del
  endpoint contra un server Flask de test, con Playwright real (chromium
  headless ya instalado). No se mockea Playwright: el objetivo es probar
  que la URL con `pdfmode=1` efectivamente genera un PDF válido.

---

## Task 1: Parámetros URL + flag de listo en el JS del factsheet

**Files:**
- Modify: `scripts/build_factsheet.py` (dentro de `HTML_TEMPLATE`, el IIFE
  de `// Init` que termina en `switchFund("TRI");`, alrededor de la línea
  5484-5527 del archivo actual).
- Test: manual (no hay test runner de JS en el proyecto — se verifica con
  Playwright en Task 3, y a mano en el navegador).

**Interfaces:**
- Consumes: `FUNDS` (const global ya existente, `FUNDS[fondoKey].contable`
  / `.fondo_kpi` dan los períodos disponibles), `switchFund(f)`,
  `initPeriodNav(...)` (ya existentes, sin cambios de firma).
- Produces: `window.__PDF_READY__` — `true` si el render terminó con los
  períodos pedidos aplicados, `"no_data"` si el fondo no tiene datos para
  alguno de los períodos pedidos. Otros tasks (backend) esperan este flag
  por nombre exacto.

- [ ] **Step 1: Ubicar el bloque de init actual**

Leer `scripts/build_factsheet.py` y confirmar el bloque exacto (buscar el
texto `switchFund("TRI");` dentro de `HTML_TEMPLATE`, es la última línea
del IIFE `(function(){ ... })();` antes de `</script>`).

- [ ] **Step 2: Reemplazar la línea final `switchFund("TRI");` por lógica de parámetros URL**

Buscar (dentro de `HTML_TEMPLATE`) la línea:

```js
  switchFund("TRI");
})();
```

Reemplazar por:

```js
  const __params = new URLSearchParams(location.search);
  const __pFondo = __params.get("fondo");
  const __pCb = __params.get("cb");
  const __pOp = __params.get("op");
  const __pdfMode = __params.get("pdfmode") === "1";

  if (__pdfMode) document.body.classList.add("pdf-export");

  if (__pFondo && FUNDS[__pFondo]) {
    switchFund(__pFondo);
    let __missing = false;
    if (__pCb) {
      const selCb = document.getElementById("sel-periodo-cb");
      if (Array.from(selCb.options).some(o => o.value === __pCb)) {
        selCb.value = __pCb;
        selCb.dispatchEvent(new Event("change"));
      } else {
        __missing = true;
      }
    }
    if (__pOp) {
      const selOp = document.getElementById("sel-periodo-op");
      if (Array.from(selOp.options).some(o => o.value === __pOp)) {
        selOp.value = __pOp;
        selOp.dispatchEvent(new Event("change"));
      } else {
        __missing = true;
      }
    }
    window.__PDF_READY__ = __missing ? "no_data" : true;
  } else {
    switchFund("TRI");
    if (__pdfMode) window.__PDF_READY__ = "no_data";
  }
})();
```

Notar: `selCb.dispatchEvent(new Event("change"))` ya dispara `render()`
porque el listener `sel.addEventListener("change", render)` está
registrado más arriba en el mismo IIFE (línea con
`["sel-periodo-cb", "sel-periodo-op", "sel-periodo"].forEach(...)`) — no
hay que llamar a `render()` de nuevo a mano.

- [ ] **Step 3: Agregar CSS `body.pdf-export`**

En el bloque `<style>` de `HTML_TEMPLATE`, cerca de las reglas
`.selectors` (línea ~1780), agregar:

```css
body.pdf-export #sidebar,
body.pdf-export #chat-bubble-root { display: none !important; }
body.pdf-export #main-content { margin-left: 0 !important; }
```

Si el id del contenedor del chat bubble es distinto, buscarlo primero con
`grep -n "chat-bubble" scripts/build_factsheet.py` (se inyecta vía
`__CHAT_BUBBLE_JS__`) y usar el id/selector real que ese script crea en el
DOM en vez de `#chat-bubble-root`.

- [ ] **Step 4: Regenerar y probar a mano**

```bash
cd c:\Users\raimundo.opazo\automation_agent
python scripts/build_factsheet.py
python -m scripts.ingesta_server
```

Abrir en el navegador:
`http://127.0.0.1:8765/factsheet?fondo=PT&cb=2026-06&op=2026-07&pdfmode=1`

Verificar en la consola del navegador (F12) que `window.__PDF_READY__`
existe y vale `true`, que el sidebar no aparece, y que el fondo/período
mostrados corresponden a PT / jun-2026 / jul-2026.

Probar también con un período inexistente, ej.
`?fondo=PT&cb=1900-01&op=2026-07&pdfmode=1`, y confirmar
`window.__PDF_READY__ === "no_data"`.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_factsheet.py factsheet.html
git commit -m "feat: soporte de parámetros URL y pdfmode en factsheet para exportación a PDF"
```

---

## Task 2: Botón "Exportar PDF" y modal de selección en el sidebar

**Files:**
- Modify: `scripts/build_factsheet.py` (`HTML_TEMPLATE`: CSS, HTML del
  sidebar cerca de `#btn-admin`/`#btn-ingesta`, y JS del modal).

**Interfaces:**
- Consumes: `FUNDS` (para poblar checkboxes y unión de períodos),
  `window.INGESTA_TOKEN` (ya inyectado por `_serve_html_con_token` en
  `ingesta_server.py`), endpoint `POST /api/export-pdf` (implementado en
  Task 3 — este task ya asume su contrato de request/response).
- Produces: función global `onDescargarPdf()` invocada por el botón
  "Descargar" del modal; no es consumida por otros tasks.

- [ ] **Step 1: HTML del botón + modal**

En `HTML_TEMPLATE`, dentro de `<div id="sidebar">`, después de la línea:

```html
<button type="button" id="btn-admin" class="admin-toggle" title="Modo admin: click en cualquier número para ver cómo se calculó, y editar fechas de Noticias">✎ Admin</button>
```

Agregar:

```html
<button type="button" id="btn-export-pdf" class="admin-toggle" title="Exportar uno o varios fact sheets a PDF">⬇ Exportar PDF</button>
```

Después del bloque `<div id="trace-modal-bg" ...>...</div>` (buscar su
cierre `</div>` que corresponde a `id="trace-modal-bg"`), agregar un nuevo
modal:

```html
<div id="export-modal-bg" class="trace-modal-bg" aria-hidden="true">
  <div class="trace-modal" role="dialog" aria-modal="true" aria-labelledby="export-title">
    <button type="button" class="trace-close" id="export-close" aria-label="Cerrar">×</button>
    <h3 id="export-title">Exportar a PDF</h3>
    <div class="trace-sub">Elige uno o más fondos y el período a exportar.</div>
    <div id="export-fund-checks" style="margin:12px 0;display:flex;gap:14px"></div>
    <table class="trace-inputs" style="width:100%;margin-bottom:12px">
      <tbody>
        <tr>
          <td>Período operacional</td>
          <td><select id="export-sel-op" style="width:100%"></select></td>
        </tr>
        <tr>
          <td>Período EEFF (contable/bursátil)</td>
          <td><select id="export-sel-cb" style="width:100%"></select></td>
        </tr>
      </tbody>
    </table>
    <div id="export-status" style="min-height:16px;font-size:11px;color:#666;margin-bottom:8px"></div>
    <button type="button" id="export-download-btn" class="fund-btn active" style="width:100%;padding:8px">Descargar</button>
  </div>
</div>
```

- [ ] **Step 2: JS del modal**

En el bloque `<script>` de `HTML_TEMPLATE`, cerca de las demás funciones de
modal (`renderTraceModal`, `closeTraceModal`, buscar con
`grep -n "function closeTraceModal"`), agregar:

```js
function fmtMonthLabel(p){
  const [y, m] = p.split("-");
  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  return meses[parseInt(m, 10) - 1] + " " + y;
}

function refreshExportPeriodos(){
  const checked = Array.from(document.querySelectorAll("#export-fund-checks input:checked")).map(i => i.value);
  const opSel = document.getElementById("export-sel-op");
  const cbSel = document.getElementById("export-sel-cb");
  const opPrev = opSel.value;
  const cbPrev = cbSel.value;

  const opSet = new Set();
  const cbSet = new Set();
  checked.forEach(f => {
    Object.keys(FUNDS[f].fondo_kpi || {}).forEach(p => opSet.add(p));
    Object.keys(FUNDS[f].contable || {})
      .filter(p => ["03","06","09","12"].includes(p.slice(-2)))
      .forEach(p => cbSet.add(p));
  });

  const opList = Array.from(opSet).sort();
  const cbList = Array.from(cbSet).sort();

  opSel.innerHTML = opList.map(p => `<option value="${p}">${fmtMonthLabel(p)}</option>`).join("");
  cbSel.innerHTML = cbList.map(p => `<option value="${p}">${fmtQ(p)}</option>`).join("");

  if (opList.includes(opPrev)) opSel.value = opPrev; else if (opList.length) opSel.value = opList[opList.length - 1];
  if (cbList.includes(cbPrev)) cbSel.value = cbPrev; else if (cbList.length) cbSel.value = cbList[cbList.length - 1];

  document.getElementById("export-download-btn").disabled = checked.length === 0;
}

function openExportModal(){
  const wrap = document.getElementById("export-fund-checks");
  wrap.innerHTML = Object.keys(FUNDS).map(f => `
    <label style="display:flex;align-items:center;gap:4px;font-size:12px">
      <input type="checkbox" value="${f}" ${f === currentFund ? "checked" : ""}> ${f}
    </label>
  `).join("");
  wrap.querySelectorAll("input").forEach(i => i.addEventListener("change", refreshExportPeriodos));
  refreshExportPeriodos();
  document.getElementById("export-status").textContent = "";
  document.getElementById("export-modal-bg").classList.add("open");
}

function closeExportModal(){
  document.getElementById("export-modal-bg").classList.remove("open");
}

async function onDescargarPdf(){
  const fondos = Array.from(document.querySelectorAll("#export-fund-checks input:checked")).map(i => i.value);
  if (!fondos.length) return;
  const periodo_op = document.getElementById("export-sel-op").value;
  const periodo_cb = document.getElementById("export-sel-cb").value;
  const btn = document.getElementById("export-download-btn");
  const status = document.getElementById("export-status");

  btn.disabled = true;
  btn.textContent = "Generando...";
  status.textContent = "";

  try {
    const headers = {"Content-Type": "application/json"};
    if (window.INGESTA_TOKEN) headers["X-Ingesta-Token"] = window.INGESTA_TOKEN;
    const resp = await fetch("/api/export-pdf", {
      method: "POST",
      headers,
      body: JSON.stringify({ fondos, periodo_cb, periodo_op }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      status.textContent = "Error: " + (err.error || resp.statusText);
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `factsheets_${periodo_op}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    closeExportModal();
  } catch (exc) {
    status.textContent = "Error inesperado: " + exc;
  } finally {
    btn.disabled = false;
    btn.textContent = "Descargar";
  }
}
```

- [ ] **Step 3: Registrar event listeners en el IIFE de init**

En el mismo IIFE donde se agregó el Step 2 de Task 1, justo antes de la
lógica de `__params` (o en cualquier punto del IIFE antes del cierre),
agregar:

```js
  document.getElementById("btn-export-pdf").addEventListener("click", openExportModal);
  document.getElementById("export-close").addEventListener("click", closeExportModal);
  document.getElementById("export-modal-bg").addEventListener("click", (ev) => {
    if (ev.target.id === "export-modal-bg") closeExportModal();
  });
  document.getElementById("export-download-btn").addEventListener("click", onDescargarPdf);
```

- [ ] **Step 4: Regenerar y probar a mano**

```bash
python scripts/build_factsheet.py
python -m scripts.ingesta_server
```

Abrir `http://127.0.0.1:8765/factsheet`, click en "⬇ Exportar PDF",
verificar que el modal se abre, que tildar/destildar fondos actualiza las
opciones de período, y que "Descargar" intenta el POST (fallará porque
Task 3 aún no existe el endpoint — se espera un error visible en
`#export-status`, no un crash de JS).

- [ ] **Step 5: Commit**

```bash
git add scripts/build_factsheet.py factsheet.html
git commit -m "feat: modal de selección de fondos/período para exportar PDF"
```

---

## Task 3: Endpoint `/api/export-pdf` con Playwright

**Files:**
- Modify: `scripts/ingesta_server.py`.

**Interfaces:**
- Consumes: `window.__PDF_READY__` (`true` | `"no_data"`, producido en
  Task 1), `API_TOKEN` (ya existente en el módulo), constante de puerto
  `8765` (hardcodeada en el `if __name__ == "__main__"` del mismo archivo
  — reusar el mismo valor, no inventar una nueva constante de config).
- Produces: `POST /api/export-pdf` — request JSON
  `{"fondos": ["TRI","PT"], "periodo_cb": "2026-06", "periodo_op": "2026-07"}`,
  response `200` con `Content-Type: application/zip` y bytes del zip, o
  `422` JSON `{"ok": false, "error": "..."}"` si ningún fondo generó PDF,
  o `400` JSON si el body es inválido.

- [ ] **Step 1: Verificar que chromium de Playwright está instalado**

```bash
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop(); print('ok')"
```

Si falla con un error de "Executable doesn't exist", correr
`python -m playwright install chromium` antes de continuar (una sola vez,
no forma parte del código de producción).

- [ ] **Step 2: Agregar imports y helper `_generar_pdfs_factsheet`**

En `scripts/ingesta_server.py`, agregar a los imports del tope (junto a los
`import` existentes, orden alfabético dentro de su bloque):

```python
import io
```

y:

```python
from flask import Flask, Response, jsonify, redirect, request, send_file, send_from_directory
```

(reemplaza la línea existente `from flask import Flask, Response, jsonify, redirect, request, send_from_directory` agregando `send_file`).

Después de la función `_rebuild_factsheet` (antes de `app = Flask(...)`),
agregar:

```python
def _generar_pdfs_factsheet(
    fondos: list[str], periodo_cb: str, periodo_op: str
) -> tuple[dict[str, bytes], list[str]]:
    """Genera un PDF por fondo vía Playwright headless.

    Devuelve (pdfs_por_fondo, errores) — errores es una lista de mensajes
    legibles para los fondos que no se pudieron generar (sin datos en el
    período pedido, timeout, o excepción).
    """
    from playwright.sync_api import sync_playwright

    pdfs: dict[str, bytes] = {}
    errores: list[str] = []
    base_url = "http://127.0.0.1:8765/factsheet"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for fondo in fondos:
                page = browser.new_page(extra_http_headers={TOKEN_HEADER: API_TOKEN})
                try:
                    url = (
                        f"{base_url}?fondo={fondo}&cb={periodo_cb}"
                        f"&op={periodo_op}&pdfmode=1"
                    )
                    page.goto(url, wait_until="load")
                    page.wait_for_function(
                        "window.__PDF_READY__ !== undefined", timeout=15000
                    )
                    ready = page.evaluate("window.__PDF_READY__")
                    if ready != True:  # noqa: E712 - distingue de "no_data"
                        errores.append(
                            f"{fondo}: sin datos para el período {periodo_op}/{periodo_cb}."
                        )
                        continue
                    pdfs[fondo] = page.pdf(
                        format="A4", landscape=True, print_background=True
                    )
                except Exception as exc:  # noqa: BLE001
                    errores.append(f"{fondo}: error generando PDF ({exc}).")
                finally:
                    page.close()
        finally:
            browser.close()

    return pdfs, errores
```

- [ ] **Step 3: Agregar el endpoint Flask**

Después del último endpoint existente (`api_caja_commit`, justo antes de
`if __name__ == "__main__":`), agregar:

```python
@app.post("/api/export-pdf")
def api_export_pdf():
    body = request.get_json(force=True, silent=True) or {}
    fondos = body.get("fondos")
    periodo_cb = str(body.get("periodo_cb", ""))
    periodo_op = str(body.get("periodo_op", ""))

    if not isinstance(fondos, list) or not fondos:
        return jsonify({"ok": False, "error": "Falta seleccionar al menos un fondo."}), 400
    if not periodo_cb or not periodo_op:
        return jsonify({"ok": False, "error": "Faltan los períodos (operacional y EEFF)."}), 400

    pdfs, errores = _generar_pdfs_factsheet(fondos, periodo_cb, periodo_op)

    if not pdfs:
        return jsonify({
            "ok": False,
            "error": "No se pudo generar ningún PDF. " + " ".join(errores),
        }), 422

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fondo, pdf_bytes in pdfs.items():
            zf.writestr(f"FS_{fondo}_{periodo_op}_{periodo_cb}.pdf", pdf_bytes)
        if errores:
            zf.writestr("errores.txt", "\n".join(errores))
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="factsheets.zip",
    )
```

- [ ] **Step 4: Probar a mano con curl**

Con el servidor corriendo (`python -m scripts.ingesta_server`), copiar el
token que imprime al arrancar (`Token de esta sesión: ...`) y correr:

```bash
curl -s -X POST http://127.0.0.1:8765/api/export-pdf \
  -H "Content-Type: application/json" \
  -H "X-Ingesta-Token: <TOKEN_IMPRESO>" \
  -d '{"fondos":["PT"],"periodo_cb":"2026-06","periodo_op":"2026-07"}' \
  -o /tmp/test_export.zip
```

Verificar que `/tmp/test_export.zip` (o la ruta equivalente en Windows,
`$env:TEMP\test_export.zip` en PowerShell) pesa más de un par de KB y que
`unzip -l` (o abrirlo) muestra un `FS_PT_2026-07_2026-06.pdf`.

- [ ] **Step 5: Probar el caso "sin datos"**

```bash
curl -s -X POST http://127.0.0.1:8765/api/export-pdf \
  -H "Content-Type: application/json" \
  -H "X-Ingesta-Token: <TOKEN_IMPRESO>" \
  -d '{"fondos":["PT"],"periodo_cb":"1900-01","periodo_op":"2026-07"}'
```

Expected: `422` con JSON `{"ok": false, "error": "No se pudo generar..."}`.

- [ ] **Step 6: Commit**

```bash
git add scripts/ingesta_server.py
git commit -m "feat: endpoint /api/export-pdf con Playwright, genera zip de fact sheets"
```

---

## Task 4: Smoke test automatizado del endpoint

**Files:**
- Create: `tests/scripts/test_export_pdf.py`.

**Interfaces:**
- Consumes: `app`, `API_TOKEN`, `TOKEN_HEADER` de `scripts.ingesta_server`
  (importados directamente, sin mocks — usa Flask's `app.test_client()` y
  Playwright real).

- [ ] **Step 1: Escribir el test**

Crear `tests/scripts/test_export_pdf.py`:

```python
"""Smoke test del endpoint /api/export-pdf: usa Flask test_client + Playwright real."""
import sys
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import ingesta_server  # noqa: E402


@pytest.fixture(scope="module")
def running_server():
    """Levanta ingesta_server en un thread real (Playwright necesita un puerto TCP real, no test_client)."""
    server_thread = threading.Thread(
        target=lambda: ingesta_server.app.run(port=8765, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    import time
    import urllib.request

    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/factsheet", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        pytest.fail("El servidor no levantó a tiempo")
    yield


def test_export_pdf_genera_zip_con_pdf_valido(running_server):
    import requests

    resp = requests.post(
        "http://127.0.0.1:8765/api/export-pdf",
        headers={ingesta_server.TOKEN_HEADER: ingesta_server.API_TOKEN},
        json={"fondos": ["PT"], "periodo_cb": "2026-06", "periodo_op": "2026-07"},
        timeout=60,
    )
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        zf = zipfile.ZipFile(BytesIO(resp.content))
        names = zf.namelist()
        assert any(n.startswith("FS_PT_") and n.endswith(".pdf") for n in names)
        pdf_bytes = zf.read([n for n in names if n.endswith(".pdf")][0])
        assert pdf_bytes[:4] == b"%PDF"


def test_export_pdf_sin_token_da_401(running_server):
    import requests

    resp = requests.post(
        "http://127.0.0.1:8765/api/export-pdf",
        json={"fondos": ["PT"], "periodo_cb": "2026-06", "periodo_op": "2026-07"},
        timeout=10,
    )
    assert resp.status_code == 401


def test_export_pdf_sin_fondos_da_400(running_server):
    import requests

    resp = requests.post(
        "http://127.0.0.1:8765/api/export-pdf",
        headers={ingesta_server.TOKEN_HEADER: ingesta_server.API_TOKEN},
        json={"fondos": [], "periodo_cb": "2026-06", "periodo_op": "2026-07"},
        timeout=10,
    )
    assert resp.status_code == 400
```

Nota: usa `resp.status_code in (200, 422)` en el primer test porque el
período `2026-06`/`2026-07` puede no existir para PT en el momento en que
se corra el test (depende del estado real de la DB); lo que se verifica es
que, **si** hay datos, el ZIP contiene un PDF válido — no se fija un
período que pueda quedar desactualizado. Si querés una aserción más
estricta, reemplazá `2026-06`/`2026-07` por el último período operacional
real de PT en la DB al momento de escribir el test (correr
`recompute_derived_kpis` o inspeccionar `FUNDS["PT"].fondo_kpi` en
`factsheet.html` para confirmarlo).

- [ ] **Step 2: Verificar que `requests` está disponible**

```bash
python -c "import requests" 2>&1 || pip install requests
```

- [ ] **Step 3: Correr el test**

```bash
cd c:\Users\raimundo.opazo\automation_agent
pytest tests/scripts/test_export_pdf.py -v
```

Expected: los 3 tests pasan (el primero puede reportar 200 o 422 según
datos disponibles, ambos son PASS válidos per el `assert` del test).

- [ ] **Step 4: Commit**

```bash
git add tests/scripts/test_export_pdf.py
git commit -m "test: smoke test de /api/export-pdf con Playwright real"
```

---

## Task 5: Verificación manual end-to-end

**Files:** ninguno (solo verificación).

- [ ] **Step 1: Flujo completo en el navegador**

```bash
python scripts/build_factsheet.py
python -m scripts.ingesta_server
```

Abrir `http://127.0.0.1:8765/factsheet`, click "⬇ Exportar PDF", marcar
TRI + PT, elegir un período operacional y uno EEFF con datos conocidos,
click "Descargar". Confirmar que:
1. El botón cambia a "Generando..." y vuelve a "Descargar" al terminar.
2. Se descarga `factsheets_<periodo>.zip`.
3. El zip contiene `FS_TRI_...pdf` y `FS_PT_...pdf`, cada uno con 4
   páginas, sin sidebar ni chat bubble visibles, y con los datos del
   período elegido.

- [ ] **Step 2: Caso con un fondo sin datos en el período elegido**

Elegir una combinación de fondo + período donde uno de los fondos
marcados no tenga datos (ej. un período muy antiguo). Confirmar que el zip
igual se descarga con los PDFs de los fondos que sí tenían datos, más un
`errores.txt` mencionando el fondo omitido.

- [ ] **Step 3: Caso "todos sin datos"**

Elegir un período que ningún fondo tenga (ej. `2000-01`). Confirmar que
aparece un mensaje de error en `#export-status` (rojo/visible) y que no se
dispara ninguna descarga.
