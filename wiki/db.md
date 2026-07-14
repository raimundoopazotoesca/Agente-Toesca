# DB del agente

Archivo: `memory/agente_toesca.db` (SQLite).

## Schema

- **Dimensiones**: `dim_fondo`, `dim_activo`, `dim_serie`, `dim_cuenta`
- **Raw** (línea por línea del proveedor, con linaje + hash idempotente): `raw_rent_roll_line`, `raw_eeff_line`, `raw_flujo_line`, `raw_er_activo_line`
- **Facts**: `fact_precio_cuota`, `fact_uf`, `fact_dividendo`
- **Derived**: `derived_kpi` (formato largo, una fila por KPI — base de dashboards)
- **Audit**: `ingest_run`, `publish_run`, `schema_version`

## Cómo acceder

Nunca con SQL crudo desde el resto del agente. Siempre vía repos en `tools/db/repo_*.py`.

```python
from tools.db.connection import get_conn
from tools.db import repo_kpi

with get_conn() as conn:
    series = repo_kpi.serie_temporal(conn, "activo", "PT", "NOI")
```

Las migraciones se aplican solas al importar `tools.memory_tools` (que importa `tools.db.connection.apply_migrations`).

## Repos disponibles

| Repo | Tabla(s) | Funciones clave |
|---|---|---|
| `repo_fondo` | dim_* | `list_fondos`, `get_fondo`, `list_activos`, `list_series`, `upsert_cuenta`, `get_cuenta` |
| `repo_rent_roll` | raw_rent_roll_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_eeff` | raw_eeff_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_flujo` | raw_flujo_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_er_activo` | raw_er_activo_line | `insert_lines`, `list_by_periodo`, `mark_superseded` |
| `repo_fact` | fact_* | `upsert_precio`/`get_precio`, `upsert_uf`/`get_uf`, `upsert_dividendo`/`list_dividendos` |
| `repo_kpi` | derived_kpi | `upsert`, `get`, `serie_temporal`, `snapshot_periodo` |
| `repo_audit` | ingest_run/publish_run | `start_*`/`finish_*`/`fail_*` |

## Idempotencia

Las tablas raw tienen `UNIQUE(file_hash, source_row)`. `insert_lines` usa `INSERT OR IGNORE` → reingestar el mismo archivo no duplica. Versión nueva (hash distinto) → `mark_superseded(file_hash)` marca el anterior.

## Tests

`pytest tests/db/ -v` (91 tests). Usan SQLite temporal vía fixture `tmp_db` en `tests/conftest.py`.

## Estado por fase

- Fase 0 (esqueleto): DONE (2026-05-25)
- Fase 1 (dual-write por dominio): EN CURSO — 5 dominios listos
- Fase 2 (backfill histórico): COMPLETO — todos los dominios poblados
- Fase 3 (inversión del flujo): pendiente
- Fase 4 (query + dashboards): EN CURSO — tools `consultar_db_*` listas y registradas

### Backfill (Fase 2)

`tools/db/backfill.py` recorre los archivos de proveedor en SharePoint y los reingesta con las mismas
funciones del flujo en vivo (idempotente). Correr con:
```
python -X utf8 -m tools.db.backfill rent_roll
```
Dominios (`python -X utf8 -m tools.db.backfill [dominio...]`):
- `rent_roll` — JLL + Tres A. 10.122 filas, 2025-09..2026-03.
- `er` — ER Viña/Curicó desde INFORME EEFF. 400 filas, 2025-12..2026-03.
- `inmosa` — flujos INMOSA (meses en columnas; usa hash_extra=periodo). 46 filas, 2026-01..2026-02.
- `uf` — UF diaria desde hoja 'UF' del CDG más reciente. 5.182 días, 2012..2026.
- `eeff` — valor cuota libro desde PDFs (regex, parcial). 4 trimestres.
- `precios` — datachart LarraínVial, 1 fetch/nemo, fin de mes. 100 filas (4 nemos × 25 meses).
- `noi` — NOI mensual REAL al 100% del activo, de la sección "NOI Real" del NOI- RCSD
  (filas "NOI Mensual": INMOSA 296, Sucden 329, PT 382, Viña 416, Apoquindo 457, Apo3001 477, Curicó 502).
  → `derived_kpi` kpi='noi_mensual' (UF). 822 valores, 2018-01..2026-02.
  **Tope automático:** se detecta el mes de cierre leyendo la última fila con valor positivo de PT
  (fila 382). Evita guardar proyecciones de meses futuros que el CDG incluye para ciertos activos.
  Metadata en `dim_activo` (migración 007): `participacion` (de hoja 'Porcentaje fondos') y `categoria`.
  Participación: INMOSA 0.43, Sucden 1.0, PT 0.333, Viña 1.0, Apoquindo 0.3, Apo3001 1.0, Curicó 0.8.
  Categorías: Oficinas (PT Torre A, Apoquindo, Apo3001), Centros Comerciales (Viña, Curicó),
  Comercial (Viña + Curicó + PT Boulevard), Residencias (INMOSA), Industrial (Sucden).
  PT se divide en Torre A (fila 387) y Boulevard/CDC (fila 388), recipe `cdg_noi_split_v1`,
  para separar Oficinas de Comercial sin duplicar PT en agregaciones de fondo/total.
  Cálculos en `tools/noi_query.py` (tool `consultar_noi`): mensual, anual, anualizado
  (YTD real + promedio histórico de meses faltantes), U12M, MoM, YoY; por activo/fondo/categoria/total,
  100% o ponderado por participación. Verificado: NOI- RCSD está al 100% (Viña 100% calza con Resumen;
  Apoquindo ×0.3 ≈ NOI económico del fondo).
- `vacancia` — m² vacantes oficiales de la hoja 'Vacancia' del CDG (fila 46=fechas mensuales día=1,
  filas 47-58=segmentos) → `derived_kpi` kpi='m2_vacantes'. 1.091 valores, 12 segmentos, 2018+.
  Mismo valor que el CDG (no recalculado). Dual-write también en `actualizar_vacancia`.
  NOTA técnica: leer en read_only iterando filas UNA vez (ws.cell() es O(n) en read_only → no usar).
- `dividendos` — desde hojas 'A&R *' del CDG (Detalle='Dividendo', col D=fecha, col I=$/cuota).
  PT+Rentas A/C/I → `fact_dividendo` (108 filas, 2018..2025). Apoquindo (sin nemotécnico) →
  `derived_kpi` kpi='dividendo_por_cuota' (6 filas).
- `uf` — UF diaria desde hoja 'UF' del CDG. 5.182 días, 2012..2026.

Lectura: `consultar_db_dividendos(nemotecnico)` además de las otras `consultar_db_*`.

### Dashboard

`tools/db/dashboard.py` genera un `dashboard.html` autocontenido (datos embebidos + Chart.js CDN):
cobertura por activo/período (heatmap), gaps a poblar, series de mercado (precios/UF/dividendos),
explorador del último período y KPIs. Regenerar:
```
python -X utf8 -m tools.db.dashboard      # o tool generar_dashboard
```
`dashboard.html` está en `.gitignore` (regenerable).

Gaps conocidos:
- `2511 Rent Roll y NOI.xlsx` (nov): hoja 'Rent Roll' vacía/ausente.
- INMOSA marzo `EEFF y FC Senior Assist Mar.26.xlsx`: estructura distinta (hoja 'Activo Pasivo EERR', sin columnas de fecha tipo date). Lo cubre el flujo en vivo.
- EEFF valor cuota: regex parcial (no siempre captura serie I).
- **dividendos**: aún sin fuente confiable definida (el parser EEFF no trae fecha/serie).

### Camino de lectura (Fase 4)

`tools/query_tools.py` expone, registradas en `registry.py` y siempre disponibles:
- `consultar_db_cobertura()` — qué hay en la DB (filas + rango de períodos por dominio). Empezar acá.
- `consultar_db_kpi(entidad_tipo, entidad_key, kpi, desde, hasta)`
- `consultar_db_precio(nemotecnico, fecha)`
- `consultar_db_rent_roll(activo_key, periodo)`
- `consultar_db_er(activo_key, periodo)`
- `consultar_db_flujo(activo_key, periodo)`

El system prompt (`agent.py`) instruye usar estas antes de abrir Excel para responder preguntas.
La DB se llena a medida que corren los flujos mensuales (o con el backfill de Fase 2).

### Dominios en dual-write (Fase 1)

| Dominio | Tool con dual-write | Destino DB |
|---|---|---|
| Precios cuota | `web_bursatil_tools.obtener_precio_cuota` | `fact_precio_cuota` |
| Valor cuota libro (EEFF) | `eeff_tools.leer_eeff` | `derived_kpi` (kpi=`valor_cuota_libro`) |
| ER Viña/Curicó | `noi_tools._actualizar_er_mall` | `raw_er_activo_line` |
| Flujos INMOSA | `noi_tools.actualizar_noi_inmosa` | `raw_flujo_line` |
| Rent roll (todos los activos) | `rentroll_tools.consolidar_rent_rolls` | `raw_rent_roll_line` |

Todos son **best-effort**: si la DB falla, el flujo de Excel sigue (nunca se rompe el entregable).

### Pendientes Fase 1

- **UF**: vive en la hoja 'UF' del CDG (Excel), no hay fuente web. Persistir cuando se toque ese flujo.
- **Dividendos EEFF**: el parser regex no trae fecha ni serie de forma confiable → no persistible aún.
- **NOI PT agregado (RR JLL)**: hoja multi-activo; se optó por persistir el rent roll detallado en su lugar (más valioso para dashboards). El NOI por activo se derivará en Fase computacional.

### Pendientes EEFF — balance histórico (`ESF.total_activo`) (2026-07)

Detectado al calcular `caja_minima` (= % de activos totales) por fondo/periodo. Estado por fondo:

- **PT**: completo. 2017 no aplica (el fondo no existía). Los "faltantes" 2019-12/2020-12/2023-12
  eran falso positivo por variante de nombre ("Total activos" plural) — resuelto con matching
  case/plural-insensitive, no requiere reingesta.
- **Apo**: completo (29/29 trimestres, 2019-03 a 2025-12). 2020-12 tenía un bug de versionado
  (`superseded_at` invertido: la fila correcta del reporte quedó marcada superseded y la incorrecta
  quedó viva) — corregido 2026-07-09 con foto EEFF del usuario (Total activo real = 42.343.358.000,
  no 125.087.458.000).
- **TRI**: **9 periodos pendientes**:
  - Sin parseo de balance (ESF) — solo hay ER/flujo, cero líneas de activo/pasivo/patrimonio:
    2017-03, 2017-06, 2017-09, 2021-03, 2021-06, 2021-09, 2023-09. Requiere volver a parsear el
    PDF fuente de esos trimestres.
  - Filas de "Total activo" duplicadas sin deduplicar (7-8 valores distintos por periodo, mezcla de
    consolidado + desglose): 2024-12, 2025-06. Requiere revisar `source_file`/hoja de cada fila para
    identificar el total correcto.
- **Apo 2026-03**: EEFF más reciente aún no ingestado a `raw_eeff_line`.

`derived_kpi` kpi=`caja_minima` (fondo, %activos: Apo 0.1%, PT/TRI 1%) ya está consolidado para todos
los periodos donde `ESF.total_activo` existe limpio (67 filas iniciales + Apo 2020-12 corregido).
Los 9 periodos de TRI y Apo 2026-03 quedan sin `caja_minima` hasta resolver el parseo.

## Jerarquía de participaciones (post migración 049)

Las participaciones del organigrama TRI viven en 3 lugares:

- **`dim_sociedad(sociedad_key, nombre, fondo_key, participacion_fondo_en_sociedad)`** — holding/vehicle intermedia. Ej: Chañarcillo→TRI (100%), Curicó SpA→TRI (80%), Senior Assist→TRI (43%).
- **`dim_activo.sociedad_key`, `dim_activo.participacion_en_sociedad`** — participación del activo dentro de su sociedad. Ej: Apo3001 dentro de Chañarcillo = 68.5%.
- **`dim_fondo.fondo_padre`, `dim_fondo.participacion_en_padre`** — un subfondo dentro de un fondo padre. Ej: PT→TRI 33.3%, Apo→TRI 30%.

Vista canónica de look-through: **`v_activo_fondo_efectivo(activo_key, fondo_key, participacion_efectiva, via)`**. `via='directa'` = activo→fondo dueño de su sociedad. `via='lookthrough'` = activo→fondo abuelo vía fondo padre. Usar esta vista para toda consolidación por fondo.

⚠️ La columna vieja `dim_activo.participacion_fondo_activo` está **deprecada** (semántica mezclada) pero se conserva porque `tools/noi_query.py` aún la lee. Migrar a la vista en Fase 3.

Spec completo: `docs/superpowers/specs/2026-05-25-db-migration-design.md`.

## Ingesta ER INMOSA (fondo TRI)

Fuente: `RAW/NOI INMOSA.xlsx` (SharePoint), hoja `Hoja1`. Formato categoría×mes
anclado en la fila con label `"INMOSA"`. Módulo: `tools/db/ingest_er_inmosa.py`.

`activo_key='INMOSA'` fijo (sin desglose por residencia individual — INMOSA
engloba 6 residencias de adulto mayor como una sola entidad para efectos de
ER/NOI). Validación de integridad obligatoria: suma de las 8 categorías debe
cuadrar exacto contra la fila "NOI Mensual" de la fuente antes de persistir
(si no cuadra, el ingest falla completo, no persiste nada).

Rango histórico ingestado: 2018-01 a 2026-03 (99 meses, 792 filas = 99 × 8
categorías). El archivo vive en OneDrive, se debe copiar a una ruta local
antes de leerlo con `openpyxl` (bloqueo de permisos si se lee directo desde
la carpeta sincronizada).

## Ingesta ER Sucden (fondo TRI)

Fuente: `RAW/NOI Sucden.xlsx` (SharePoint), hoja `Hoja1`. Formato categoría×mes
anclado en la fila con label `"Sucden"` — a diferencia de INMOSA, el header de
fechas está en la MISMA fila que la ancla (no 2 filas arriba). Módulo:
`tools/db/ingest_er_sucden.py`.

`activo_key='Sucden'` fijo (Bodegas Maipú, industrial, sociedad Inmobiliaria
Chañarcillo Ltda, participación 1.0). 4 categorías: Ingresos por Arriendos,
Contribuciones, Sobretasa, Seguros. Misma validación de integridad que INMOSA
(suma de componentes == "NOI Mensual", falla atómica si no cuadra).

Rango histórico ingestado: 2018-01 a 2026-08 (104 meses, 416 filas = 104 × 4
categorías) — incluye meses futuros al mes en curso porque el arriendo es
fijo/UF-indexado con reajustes escalonados (valores planos por años, confirmado
no es arrastre erróneo de fórmula). Mismo bloqueo de OneDrive que INMOSA:
copiar a ruta local antes de leer con `openpyxl`.

**Corrección manual — Sobretasa fija 140 UF desde 2026-01**: el usuario
confirmó que a partir de enero 2026 la Sobretasa es un monto fijo de -140 UF
(no viene del archivo fuente, que trae un valor recalculado obsoleto). Aplicado
con `tools/db/correct_er_sucden_sobretasa_2026.py`: supersede las filas
`SUCDEN_SOBRETASA` con periodo >= 2026-01 e inserta las corregidas bajo
`ingest_run.tool='correction_er_sucden_sobretasa'` (file_hash sintético
`correction:sucden_sobretasa_2026`, idempotente). **Importante**: si se
re-ingesta `NOI Sucden.xlsx` en el futuro con `ingest_er_sucden.persist()`,
esta corrección queda superseded por las filas del archivo — hay que
re-aplicar el override tras cada re-ingesta hasta que la fuente misma
refleje el monto fijo.
