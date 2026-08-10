# Mercado de Bodegas — ingesta + wiring gráficos página 3 TRI

## Contexto

El factsheet TRI página 3 tiene dos elementos de "Mercado Bodegas" ya
maquetados en `build_factsheet.py` pero alimentados con placeholders:

- Tabla `tbl-bodegas` (Zona / Producción / Inventario Final / Vacancia % /
  Arriendo UF/m²), zonas fijas `Centro, Nor-Poniente, Norte, Poniente, Sur` +
  total `Gran Santiago`.
- Gráfico `chart-bodegas` (barras UF/m² + línea vacancia %, semestral) —
  `renderBodegasChart()` ya existe y ya espera exactamente
  `{semestres, uf_m2, vacancia_pct}`; solo falta pasarle datos reales.

Es el mismo patrón que "Mercado Oficinas" (`raw_mercado_oficinas` +
`raw_mercado_oficinas_evolucion`, ingeridos vía `tools/db/ingest_mercado.py` y
la pestaña "Mercado Oficinas" de `web/ingesta.html`).

## Fuentes de datos

**1. Snapshot semestral (tabla, texto pegado del informe GPS Property)**

Formato de fila (una zona por línea, "Clase" siempre "A/B"):

```
Centro A/B - 289.789 4,6% 1.340 0,5% - -1.340 0,226 9,21
```

Columnas en orden: `zona`, `clase`, `produccion_m2`, `inventario_final_m2`,
`participacion_pct`, `vacancia_actual_m2`, `tasa_vacancia_pct`,
`vacancia_anterior_m2`, `absorcion_m2`, `precio_uf_m2`, `precio_usd_m2`.
`"-"` = null. Fila final `Gran Santiago` = total (`es_total=1`, sin clase).

Zonas esperadas (fijas, igual a lo ya wireado):
`Centro, Nor-Poniente, Norte, Poniente, Sur` + `Gran Santiago`.

**2. Histórico semestral (una sola carga, no recurrente)**

Archivo `RAW/mercado bodegas db.xlsx` (ya existe en SharePoint), hoja
`Hoja1`: fila 3 = headers (`UF/m2`, `Vacancia` en col D/E), filas 4+ =
`semestre` (col C, ej. `"2S-2015"`), `uf_m2` (col D), `vacancia_pct` (col E,
fracción). 24 filas, `2S-2015`..`1S-2025` — calza exacto con el gráfico
actual del factsheet.

Este archivo **no se vuelve a tocar**: es solo el vehículo para poblar la DB
una vez. El script de carga se corre una vez (y se puede re-correr si el
archivo se actualiza a mano en el futuro — idempotente por `file_hash`), pero
no forma parte de ningún flujo mensual/recurrente. El gráfico siempre lee de
la DB, nunca del xlsx.

## Diseño

### Schema (nueva migración)

```sql
-- raw_mercado_bodegas: snapshot semestral por zona (informe GPS Property)
CREATE TABLE raw_mercado_bodegas (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo              TEXT NOT NULL,   -- 'YYYY-MM', mes de cierre del semestre (06/12)
    zona                 TEXT NOT NULL,   -- 'Centro'|'Nor-Poniente'|'Norte'|'Poniente'|'Sur'|'Gran Santiago'
    clase                TEXT,            -- 'A/B' (null para el total)
    es_total             INTEGER DEFAULT 0,
    produccion_m2        REAL,
    inventario_final_m2  REAL,
    participacion_pct    REAL,            -- 4.6, no 0.046
    vacancia_actual_m2   REAL,
    tasa_vacancia_pct    REAL,
    vacancia_anterior_m2 REAL,
    absorcion_m2         REAL,
    precio_uf_m2         REAL,
    precio_usd_m2        REAL,
    file_hash            TEXT,
    source_row           INTEGER,
    ingest_run_id         INTEGER REFERENCES ingest_run(id),
    loaded_at             TEXT DEFAULT (datetime('now')),
    superseded_at         TEXT,
    UNIQUE(file_hash, source_row)
);
CREATE INDEX idx_mercado_bodegas_periodo ON raw_mercado_bodegas(periodo);
CREATE INDEX idx_mercado_bodegas_lookup ON raw_mercado_bodegas(periodo, zona)
    WHERE superseded_at IS NULL;

-- raw_mercado_bodegas_evolucion: histórico semestral UF/m² + vacancia
-- (carga única desde RAW/"mercado bodegas db.xlsx", ver tools/db/backfill_mercado_bodegas_evolucion.py)
CREATE TABLE raw_mercado_bodegas_evolucion (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    semestre      TEXT NOT NULL,   -- '2S-2015', '1S-2016', ...
    anio          INTEGER NOT NULL,
    periodo_num   INTEGER NOT NULL,  -- 1|2
    uf_m2         REAL,
    vacancia_pct  REAL,            -- fracción, 0.0995 = 9.95%
    source_file   TEXT,
    file_hash     TEXT,
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT,
    UNIQUE(semestre, file_hash)
);
CREATE INDEX idx_mercado_bodegas_evolucion_semestre
    ON raw_mercado_bodegas_evolucion(semestre);
```

### `tools/db/ingest_mercado_bodegas.py`

Mirror de `tools/db/ingest_mercado.py`: `parse_tabla_bodegas(texto)`,
`validate(texto, periodo)`, `commit(texto, periodo)`. Sin parámetro
`proveedor` (una sola fuente, GPS Property). Reglas:

- Parser tolera `"-"` → `None` en cualquier columna numérica.
- Valida que las 6 zonas esperadas estén presentes (5 zonas + Gran Santiago),
  sin sobrantes ni faltantes.
- `tasa_vacancia_pct` en rango `0-100`.
- Campos de superficie/precio no negativos salvo `absorcion_m2` (puede ser
  negativa).
- Mismo patrón de idempotencia: `file_hash` sobre `f"{periodo}|{texto.strip()}"`,
  `superseded_at` al reemplazar un período ya cargado.

### `tools/db/backfill_mercado_bodegas_evolucion.py`

Script de una sola corrida (no ingest recurrente, no expone validate/commit
en la UI). Lee el xlsx con `openpyxl` (`iter_rows` una vez), parsea
`semestre` → `anio`/`periodo_num`, inserta si no existe (`UNIQUE(semestre,
file_hash)`), marca `superseded_at` en filas previas del mismo semestre con
hash distinto si se re-corre tras editar el archivo a mano.

CLI: `python -X utf8 -m tools.db.backfill_mercado_bodegas_evolucion` (path
default apunta a `RAW/mercado bodegas db.xlsx` vía `SHAREPOINT_DIR`, igual
que `ingest_mercado_oficinas_evolucion.py`).

### `scripts/ingesta_server.py`

Nuevos endpoints, mismo patrón que los de oficinas:

- `GET /api/mercado/bodegas/periodo_check?periodo=YYYY-MM`
- `POST /api/mercado/bodegas/validate` `{texto, periodo}`
- `POST /api/mercado/bodegas/commit` `{texto, periodo}` → `_rebuild_factsheet()`

### `web/ingesta.html`

- Renombrar el tab `Mercado Oficinas` (`data-tab="mercado"`) a **`Mercado`**.
- Dentro del panel `tab-mercado`, agregar sub-tabs internos (mismo patrón CSS/JS
  que `er-subtabs` en "Ingresos/NOI Activos"): **Oficinas** (contenido actual,
  sin cambios) / **Bodegas** (nuevo formulario).
- Formulario Bodegas: selector de período semestral (`1S-YYYY`/`2S-YYYY`,
  no trimestral), textarea para pegar la tabla GPS Property, preview con
  columnas `Zona | Clase | Producción | Inventario Final | Participación % |
  Vacancia Actual m² | Tasa Vacancia % | Vacancia Anterior | Absorción |
  Precio UF/m² | Precio US$/m²`, botón confirmar. JS calcado del bloque
  `lastMercado*` / `renderMercadoPreview` existente, con prefijo `mercadoBodegas`.
- Ajustar el listener de `location.hash === '#mercado'` si aplica (sigue
  abriendo el tab consolidado; el sub-tab default queda en Oficinas).

### `scripts/build_factsheet.py`

- `_fetch_bodegas_mercado(db_path, periodo=None)`: lee último período de
  `raw_mercado_bodegas` (`superseded_at IS NULL`), ordenado por el orden fijo
  de zonas del `cfg["bodegas"]["zonas"]`, retorna filas + total. Se agrega a
  `F.mercado_bodegas` en `fetch_fondo()` (TRI únicamente).
- `_fetch_bodegas_evolucion(db_path)`: lee `raw_mercado_bodegas_evolucion`
  ordenado por `(anio, periodo_num)`, retorna `{semestres, uf_m2, vacancia_pct}`
  (vacancia ya en %, multiplicar por 100 al leer). Se agrega a `F.bodegas_evolucion`.
- En el JS embebido (línea ~7390-7404): reemplazar el bloque que arma
  `tbl-bodegas-tbody` y `chart-bodegas` desde `S.page3.bodegas` (placeholder)
  por lectura de `F.mercado_bodegas` / `F.bodegas_evolucion`, llamando a
  `renderBodegasChart("chart-bodegas", F.bodegas_evolucion)` igual que ya se
  hace para oficinas con `of`.
  - Si `F.mercado_bodegas` es `None` (sin datos aún) o `F.bodegas_evolucion`
    es `None`, mantener el placeholder actual (no romper el build cuando no
    hay ingesta todavía).
  - Los párrafos de texto (`txt-mercado3-bodegas-1/2`) quedan placeholder —
    fuera de alcance.

## Fuera de alcance

- Auto-generación de los párrafos de comentario de bodegas.
- Cualquier actualización recurrente del xlsx de evolución — es un input de
  una sola vez para poblar la DB.
- Vacancia bodegas de Apoquindo/PT (ya cubierta por `v_vacancia_*` en otro
  dominio, no relacionado a este informe de mercado externo).

## Testing

- `tests/db/test_ingest_mercado_bodegas.py`: parser (formato válido, `"-"` →
  null, zonas faltantes/sobrantes, rango vacancia), idempotencia commit x2.
- `tests/db/test_backfill_mercado_bodegas_evolucion.py`: parseo del xlsx real
  (fixture con las mismas 3-5 filas de ejemplo), idempotencia.
- `tests/test_ingesta_server_mercado_bodegas.py`: endpoints validate/commit,
  mirror de `tests/test_ingesta_server_mercado.py`.
- `tests/test_build_factsheet_mercado.py`: extender con caso bodegas
  (datos presentes → tabla/gráfico poblados; ausentes → placeholder).
