# Exportar Fact Sheet a PDF

## Objetivo

Agregar un botón "Exportar PDF" al factsheet HTML que abre un pop-up donde el
usuario elige uno o más fondos (TRI/PT/Apo) y un período operacional + un
período EEFF (contable/bursátil), y descarga un `.zip` con un PDF por cada
fondo seleccionado, renderizado tal como se ve en pantalla (4 páginas).

## Alcance

- Botón + modal en el sidebar del factsheet (`scripts/build_factsheet.py`,
  dentro de `HTML_TEMPLATE`).
- Endpoint nuevo `/api/export-pdf` en `scripts/ingesta_server.py`.
- Soporte de parámetros URL (`?fondo=&cb=&op=&pdfmode=1`) para que el
  render pueda dispararse sin interacción manual.
- Fuera de alcance: exportar a otros formatos, programar envíos automáticos,
  fechas independientes por fondo.

## Frontend (`HTML_TEMPLATE`)

### Botón y modal

- Botón "Exportar PDF" en el sidebar, junto a "Ingesta FS" / "✎ Admin".
- Modal (mismo patrón visual que `trace-modal` ya existente) con:
  - Checkboxes de fondo: TRI, PT, Apo (multi-select, al menos uno).
  - Selector de período operacional (mensual) — reusa la lista de
    `Object.keys(F.fondo_kpi)` unida entre los fondos marcados.
  - Selector de período EEFF (trimestral, contable/bursátil) — reusa
    `Object.keys(F.contable)` filtrado a meses `03/06/09/12`, unido entre
    los fondos marcados.
  - Botón "Descargar" (deshabilitado si no hay fondo marcado).
- Al tildar/destildar un fondo, los selectores de período se repueblan con
  la unión de períodos disponibles de los fondos marcados en ese momento.
- Si el usuario elige una fecha que no existe para alguno de los fondos
  marcados, ese fondo simplemente se omite en el resultado (ver backend);
  no se bloquea la selección en el frontend.

### Flujo de descarga

```js
async function onDescargarPdf(){
  const body = { fondos: [...seleccionados], periodo_cb, periodo_op };
  const resp = await fetch("/api/export-pdf", {
    method: "POST",
    headers: {"Content-Type":"application/json", "X-Ingesta-Token": TOKEN},
    body: JSON.stringify(body)
  });
  if (!resp.ok) { /* mostrar error */ return; }
  const blob = await resp.blob();
  // trigger download via <a> temporal + URL.createObjectURL
}
```

- Botón muestra estado "Generando..." (deshabilitado) mientras espera la
  respuesta — puede tardar varios segundos por cada combinación fondo.

### Modo `pdfmode=1` (para Playwright)

- `init()` lee `URLSearchParams(location.search)`:
  - `fondo` → llama `switchFund(fondo)` en vez de default `"TRI"`.
  - `cb` / `op` → tras `switchFund`, setea `sel-periodo-cb`/`sel-periodo-op`
    si el valor existe entre las opciones, dispara `change` → `render()`.
  - `pdfmode=1` → agrega clase `pdf-export` a `<body>`.
- CSS `body.pdf-export`: oculta `#sidebar` y el chat bubble (mismo patrón
  que reglas `.hidden` existentes), y expande `#main-content` a todo el
  ancho.
- Tras completar `render()` (y el `switchFund`/período inicial si vinieron
  por URL), el script setea `window.__PDF_READY__ = true`. Este flag es lo
  que Playwright espera (`page.wait_for_function("window.__PDF_READY__")`)
  antes de imprimir.
- Sin `pdfmode=1` el comportamiento actual no cambia (default `switchFund("TRI")`,
  sidebar visible).

## Backend (`scripts/ingesta_server.py`)

### `POST /api/export-pdf`

- Requiere `X-Ingesta-Token` (igual que el resto de `/api/*`).
- Body: `{"fondos": ["TRI","PT"], "periodo_cb": "2026-06", "periodo_op": "2026-07"}`.
- Por cada fondo:
  1. Construye URL `http://127.0.0.1:{PUERTO}/factsheet?fondo=X&cb=Y&op=Z&pdfmode=1`.
  2. Abre con Playwright (`sync_playwright`, chromium headless), setea el
     header `X-Ingesta-Token` en la página, navega, `wait_for_function("window.__PDF_READY__ === true", timeout=15000)`.
  3. Si el `wait_for_function` da timeout (fondo/fecha sin datos → la página
     nunca llega a un estado renderizable, o tira error JS), se captura la
     excepción, se omite ese fondo y se agrega una línea a `errores.txt`.
  4. `page.pdf(format="A4", landscape=True, print_background=True)` → bytes.
- Un solo browser Playwright se lanza una vez por request y se reutiliza
  entre fondos (una `page` nueva por fondo, mismo `browser`), para no pagar
  el costo de arranque N veces.
- Arma un `.zip` en memoria (`io.BytesIO` + `zipfile.ZipFile`) con
  `FS_<fondo>_<cb>_<op>.pdf` por cada fondo exitoso, más `errores.txt` si
  hubo omisiones.
- Devuelve `send_file(..., mimetype="application/zip", download_name="factsheets.zip")`.
- Si los 3 fondos fallan → 422 con JSON de error (nada que descargar).

### Dependencias

- `playwright` ya está instalado (`pip show playwright` → 1.58.0). Verificar
  que el browser chromium esté instalado (`playwright install chromium`) —
  si falta, el endpoint debe devolver un error claro indicando el comando a
  correr, no un 500 críptico.

## Manejo de errores

- Fondo sin datos en el período pedido → omitido silenciosamente del ZIP,
  reportado en `errores.txt` dentro del mismo ZIP.
- Todos los fondos fallan → 422, sin ZIP.
- Timeout de Playwright por fondo → mismo tratamiento que "sin datos".
- Token inválido/ausente → 401 (ya cubierto por `_require_token` existente).

## Testing

- Manual: correr `ingesta_server.py`, abrir `/factsheet`, exportar 1 fondo,
  2 fondos, los 3, con y sin datos en el período elegido; abrir el ZIP y
  verificar que el PDF tiene las 4 páginas y se ve como en pantalla.
- Manual: probar `?fondo=PT&cb=2026-06&op=2026-07&pdfmode=1` directo en el
  navegador y confirmar que carga sin sidebar y sin necesitar clicks.
