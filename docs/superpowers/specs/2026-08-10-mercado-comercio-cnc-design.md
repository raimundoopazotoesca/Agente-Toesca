# Mercado Comercio (CNC) — tabla "Variaciones Reales Acumuladas Total Locales RM"

## Contexto

La página 3 del fact sheet TRI ("Análisis de Mercado") tiene una sección
`centros_comerciales` con la tabla "Variaciones Reales Acumuladas Total
Locales RM (CNC)" — 7 columnas (Total Comercio, Vestuario, Calzado,
Artefactos Eléctricos, Línea Hogar, Muebles, Supermercados) y hoy solo
renderiza placeholders (`build_factsheet.py` ~línea 7606-7611,
`S.page3.centros_comerciales.categorias`).

Fuente del dato: informes mensuales de CNC (Cámara Nacional de Comercio),
gráfico "Ventas del Comercio Acumuladas" del PDF `Ventas-Comercio-RM-<mes>-<año>.pdf`.
El usuario ya armó un Excel histórico (`CNC_Historico_Variaciones_Reales_Acumuladas_RM_2025-2026.xlsx`,
hoja "Histórico publicado") con 18 meses (Ene 2025 - Jun 2026) de estos
valores. A futuro, cada mes se ingesta a mano vía una nueva sección
"Supermercados" en la página de ingesta de mercado (`web/ingesta.html`),
pidiendo explícitamente al usuario los 7 valores con instrucciones de dónde
buscarlos.

Sigue el mismo patrón ya usado para `raw_mercado_bodegas` (paste-text +
validate/commit vía `ingesta_server.py` + subtab en `web/ingesta.html`).

## Alcance

1. Tabla nueva `raw_mercado_comercio` — solo período + las 7 categorías
   (sin fuente/URL/referencia; confirmado con el usuario que no se
   necesitan para esta tabla).
2. Carga única (backfill) de las 18 filas del Excel histórico.
3. Módulo de ingesta paste-text (`validate`/`commit`) para meses futuros,
   sin fuente, mismo estilo que `ingest_mercado_bodegas.py`.
4. Endpoints Flask en `ingesta_server.py` (mismo patrón que bodegas:
   `periodo_check`, `validate`, `commit`).
5. Subtab "Supermercados" en `web/ingesta.html`, con las instrucciones de
   búsqueda explícitas dadas por el usuario.
6. `build_factsheet.py`: reemplazar el placeholder de
   `tbl-comercio-tbody` por el fetch real desde la DB — una sola fila (el
   mes operacional vigente del fact sheet, no histórico completo).

## Datos

### Schema — `raw_mercado_comercio`

```sql
CREATE TABLE raw_mercado_comercio (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo                 TEXT NOT NULL,   -- 'YYYY-MM'
    categoria               TEXT NOT NULL,   -- una de las 7 fijas (ver abajo)
    variacion_acumulada_pct REAL,            -- fracción: 0.007 = 0,7%
    file_hash               TEXT,
    source_row              INTEGER,
    ingest_run_id           INTEGER REFERENCES ingest_run(id),
    loaded_at               TEXT DEFAULT (datetime('now')),
    superseded_at           TEXT,
    UNIQUE(periodo, categoria, file_hash)
);

CREATE INDEX idx_mercado_comercio_periodo ON raw_mercado_comercio(periodo);
CREATE INDEX idx_mercado_comercio_lookup ON raw_mercado_comercio(periodo, categoria)
    WHERE superseded_at IS NULL;
```

Categorías fijas (mismo orden/strings que `centros_comerciales.categorias`
en `build_factsheet.py`):
`Total Comercio, Vestuario, Calzado, Artefactos Eléctricos, Línea Hogar, Muebles, Supermercados`.

Nota: en el Excel la columna se llama "Supermercado Tradicional"; en el
fact sheet la columna se llama "Supermercados" — mapear al ingestar/leer.

### Backfill histórico

Script de un solo uso `tools/db/backfill_mercado_comercio.py`:
lee la hoja "Histórico publicado" del Excel
(`C:\Users\raimundo.opazo\Downloads\CNC_Historico_Variaciones_Reales_Acumuladas_RM_2025-2026.xlsx`),
fila 5 = encabezado, filas 6-23 = los 18 meses, columnas `Total Comercio`
... `Supermercado Tradicional`. Inserta 18 × 7 = 126 filas en
`raw_mercado_comercio` (sin fuente/URL/referencia).

### Ingesta mensual futura (paste-text)

`tools/db/ingest_mercado_comercio.py` con `validate(texto, periodo)` /
`commit(texto, periodo)`, mismo estilo que `ingest_mercado_bodegas.py`:
una línea con las 7 categorías separadas por espacio/tab, tokens en el
mismo orden que las columnas del Excel/PDF, "-" como null, formato
numérico chileno con "%" (`0,7%` → `0.007`).

No expone CLI; lo consume `scripts/ingesta_server.py` (Flask), igual que
bodegas/oficinas.

## Backend — `ingesta_server.py`

Tres endpoints nuevos, espejo exacto de los de bodegas:

- `GET /api/mercado/comercio/periodo_check?periodo=YYYY-MM`
- `POST /api/mercado/comercio/validate` — `{texto, periodo}`
- `POST /api/mercado/comercio/commit` — `{texto, periodo}`

## Frontend — `web/ingesta.html`

Tercer botón en `#mercado-subtabs`: `data-mercadotab="comercio"` → panel
`#mercado-panel-comercio`.

El panel debe mostrar, antes del textarea de pegado, el bloque de
instrucciones tal cual las dio el usuario:

> Buscar en Google: `site:cnc.cl/wp-content/uploads/ "Ventas-Comercio-RM" "<Mes> <Año>"`,
> entrar al PDF y usar el gráfico "Ventas del Comercio Acumuladas".

(el `<Mes> <Año>` se arma dinámicamente a partir del selector de período,
igual que ya hacen otras secciones de esta página con el mes vigente).

Selector de período mensual (no trimestral/semestral como oficinas/bodegas)
+ textarea para pegar la fila de 7 valores + botones validar/confirmar,
igual estructura JS que el bloque de bodegas (`lastMercadoBod...` →
`lastMercadoComercio...`).

## Fact sheet — `build_factsheet.py`

- Nueva función `_fetch_mercado_comercio(db_path, periodo)` → dict
  `{categoria: variacion_pct}` para el período exacto (sin fallback a
  período anterior — si no está ingestado, se muestra placeholder, igual
  criterio que bodegas cuando `bodRows` es None).
- En el fetch de datos del fondo TRI: `mercado_comercio_por_periodo` /
  `F.mercado_comercio`, análogo a `F.mercado_bodegas`.
- En el render (reemplaza líneas ~7606-7611): si hay datos para
  `usadoOp`, pintar la fila con los 7 valores formateados como
  `+0,7%` / `-4,5%` (signo explícito, 1 decimal, mismo criterio visual que
  la imagen de referencia); si no, mantener la fila de placeholders
  actual.

## Fuera de alcance

- No se agrega columna de fuente/URL/referencia (confirmado con el
  usuario).
- La tabla del fact sheet sigue mostrando una sola fila (mes operacional
  vigente), no histórico completo — el histórico vive en la DB para
  soportar refactors futuros, pero no se renderiza como serie.
- No se automatiza el scraping del PDF de CNC — la ingesta mensual sigue
  siendo manual (paste-text), con las instrucciones de búsqueda como guía
  para el usuario.
