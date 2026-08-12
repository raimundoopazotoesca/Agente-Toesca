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

## Ocupación por residencia INMOSA (migración 082)

Fuente: `RAW/Ocupacion Acalis - <mes> <año> - Toesca.xlsx` (SharePoint), 9
hojas (una por residencia: Candil, Colombia, Coventry, Errazuriz, Medina,
Montahue, Montemar, VA - Cordillera, VA - Valle). Módulo:
`tools/db/ingest_ocupacion_residencia.py`.

`INMOSA` en `dim_activo`/`raw_er_activo_line` es un solo activo agregado
(fondo TRI, participación 0.43) sin desglose por residencia — esta tabla
agrega esa granularidad fina solo para ocupación. Nueva tabla `dim_residencia`
(residencia_key, nombre, activo_key, camas, vigente_hasta) — mismo patrón que
`dim_sociedad`.

Dos formatos de hoja en la fuente: A (Mes/Año, Residentes, Ocupación%) y B
(+ Ingresos/Egresos/Fallecimiento, + fila "Total" final que se excluye del
ingest por no ser un período real). `ocupacion_pct` se **recalcula siempre**
como `cantidad_residentes/camas` (decisión del usuario 2026-08-12) — el % que
trae la fuente puede venir inconsistente (ej. Colombia mar-2026: fuente=102%
vs recalculado=101,9%; Coventry abr-2025 traía coma decimal chilena "98,4").
El valor crudo se preserva en `ocupacion_pct_fuente` solo para auditoría.

**Montahue, Montemar, VA - Cordillera, VA - Valle están vendidas** (confirmado
por el usuario 2026-08-12, fuera del portafolio actual) — se sigue ingestando
su histórico para gráficos, marcadas con `dim_residencia.vigente_hasta` =
último período con datos en la fuente (2020-02 en las 4, proxy de fecha de
venta real desconocida).

Vistas: `v_ocupacion_inmosa_consolidado` (todas las residencias con datos en
cada período, refleja el portafolio real de cada momento) y
`v_ocupacion_inmosa_vigente` (excluye las 4 vendidas en todo el histórico,
para comparar el portafolio actual contra sí mismo sin el salto al venderlas).

`UNIQUE(file_hash, residencia_key, source_row)` — no solo `(file_hash,
source_row)`, porque `source_row` se repite entre hojas del mismo archivo
(todas arrancan en fila 6); con la constraint vieja el `INSERT OR IGNORE`
descartaba filas legítimas de residencias distintas como si fueran duplicadas.

Rango histórico ingestado: 732 filas, Candil 2015-09..2026-03 (la serie más
larga) hasta VA - Valle/Cordillera 2018-10..2020-02 (las más cortas, vendidas).

**Flujo de ingesta recurrente**: `python -X utf8 -m tools.db.backfill ocupacion`
(o `python -X utf8 -m tools.db.backfill` sin argumentos, incluido en la lista
por defecto) — busca el archivo `RAW/Ocupacion Acalis*.xlsx` más reciente por
nombre y lo reingesta. Idempotente (no duplica si no cambió). Cuando llegue
una planilla nueva con más meses, basta con reemplazar el archivo en RAW/ y
correr el comando — el hash distinto dispara `superseded_and_reinserted`.

**Pestaña "Ocupación INMOSA" en el menú de ingesta web** (`http://127.0.0.1:8765/ingesta`):
dropzone sin selector de período (la planilla trae el histórico completo) →
validar (muestra residencias/rango/anomalías) → confirmar e ingestar. Wraper
`tools/db/ingest_ocupacion_web.py` (validate/commit sobre
`ingest_ocupacion_residencia.py`), endpoints `/api/ocupacion/status`,
`/validate`, `/commit` en `scripts/ingesta_server.py`. Aparece también en el
dashboard de cobertura de la pestaña Inicio (`tools/db/estado_ingesta.py`,
`CONFIG` id=`ocupacion_inmosa`, mensual, solo las 5 residencias vigentes con
hoja en la fuente — "Domingo Calderón", 146 camas, es parte del portafolio
actual pero aún no tiene hoja en esta planilla, gap conocido).

**Wireado en el fact sheet TRI (`scripts/build_factsheet.py`)**: página 6
(INMOSSA), gráfico "Ocupación (2018–2026)" bajo la tabla de residencias.
`fetch_fondo()` arma `page6_data.ocupacion_inmosa` desde
`v_ocupacion_inmosa_vigente` (solo las 6 residencias del portafolio actual,
2018 en adelante — decisión del usuario 2026-08-12), pivotado a
`{years: [...], series: {año: [12 valores mensuales o null]}}`. Render JS:
`renderOcupacionInmosaChart()`, una línea por año (paleta fija
`OCUPACION_INMOSA_PALETTE`, 9 colores para 2018-2026), año más reciente con
etiquetas de valor sobre cada punto — mismo estilo visual que el histórico de
ocupación de Control de Gestión.

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

**Regla de negocio permanente — Sobretasa fija -140 UF desde 2026-01**: el
usuario confirmó que a partir de enero 2026 la Sobretasa es un monto fijo,
independiente de lo que traiga la fuente (que sigue trayendo un valor
recalculado obsoleto). La regla está baked-in en `ingest_er_sucden.
parse_planilla` (constantes `_SOBRETASA_FIJA_DESDE`/`_SOBRETASA_FIJA_VALOR`):
la validación de integridad NOI corre contra los valores originales de la
fuente, y el override se aplica DESPUÉS, solo al monto persistido. Esto
significa que cualquier re-ingesta futura de `NOI Sucden.xlsx` aplica el
fijo automáticamente — no requiere reprocesar el override a mano.

El estado actual de la DB (416 filas + 8 corregidas) se corrigió una vez con
`tools/db/correct_er_sucden_sobretasa_2026.py` (script de corrección puntual,
ya ejecutado — se mantiene solo como registro de auditoría, no hace falta
volver a correrlo).

## Ingesta ER Viña Centro (activo, fondo TRI)

Fuente: `RAW/NOI VIÑA.xlsx` (SharePoint), hoja `Hoja1`, bloque de input manual
(fila 124 en adelante: "Ingreso de Explotacion"). Módulo:
`tools/db/ingest_er_vina.py`. `activo_key='Viña Centro'`.

**Diferencia clave vs. INMOSA/Sucden/PT/Apoquindo**: esos activos traen la
planilla ya agregada por categoría y en UF. Viña Centro trae ~70 cuentas
contables individuales en **pesos crudos**, y la lista de cuentas no es
estable en el tiempo (se agregan cuentas nuevas, ej. "CUOTA INCORPORACIÓN
FONDO PROMOCIÓN" desde 2026-01). Por eso el `cuenta_codigo` se extrae por
regex del código contable en columna C (`^\d(?:-\d{1,3}){3}`) en vez de un
diccionario fijo de categorías.

**Conversión CLP→UF**: se hace en el parser mismo (a diferencia de los demás,
que reciben la fuente ya en UF), usando `fact_uf` de la DB (UF de fin de mes,
decisión del usuario 2026-07-14) — **no** la UF que trae la propia planilla.

**Definición de NOI (confirmada por el usuario 2026-07-14)**: `SUM(monto_uf)
WHERE es_operacional=1`, es decir Ingreso Explotación + Gastos de
Administración y Ventas, **sin** Ingreso Fuera de Explotación. La planilla
fuente NO calcula esto bien en ninguna de sus 2 filas de NOI propias:
- Fila 87 "Total Operacional" = Total Gastos Admin y Ventas + Total Ingresos,
  y Total Ingresos = Resultado Operación + Fuera de Explotación → queda
  contaminada con ingresos no operacionales.
- Fila 119 "Noi" (Sección 2 de la planilla) tiene referencias UF incorrectas
  entre sep-2023 y ene-2025 (bug confirmado por el usuario), resta gastos de
  más.

Por eso el parser recalcula el NOI desde las cuentas crudas, sin reusar
ninguna fórmula de la planilla. Validación de integridad por periodo: suma de
cuentas Ingreso Explotación == "Total Resultado Operación" (fila 142), y suma
de cuentas Gastos Admin y Ventas == "Total Gastos de administración y ventas"
(fila 205) — ambas con tolerancia de 2000 CLP (residuo de redondeo
irrelevante frente a subtotales de decenas de millones).

**Overrides de datos faltantes en la fuente** (confirmados por el usuario
2026-07-14, constante `_OVERRIDES_MONTO_CLP` en el módulo): la fuente trae,
para ciertas cuentas y periodos puntuales, la fila de categoría (header) con
el total correcto pero la cuenta hija en blanco:
- `3-1-10-120` (SEGURIDAD PARKING): en blanco jul-nov 2025.
- `3-1-40-102` (CONTRIBUCIONES): en blanco abr-may 2026.

Cualquier re-ingesta futura de `NOI VIÑA.xlsx` aplica estos overrides
automáticamente. Si aparecen gaps nuevos del mismo tipo (header con total
correcto, cuenta hija en blanco), la validación de integridad los detecta y
el ingest falla — hay que pedirle al usuario el desglose real y agregarlo a
`_OVERRIDES_MONTO_CLP`.

Rango histórico ingestado: 2023-08 a 2026-05 (34 meses, 1768 filas).

**Nota — reemplaza la ingesta anterior de `actualizar_er_vina`**: existía una
ingesta previa a `raw_er_activo_line` vía `noi_tools.actualizar_er_vina`
(dual-write desde el ER Viña embebido en el CDG mensual, un mes a la vez, 4
meses cargados: dic-2025 a mar-2026, ~71-72 filas c/u). El `persist()` de
`ingest_er_vina` marcó esas filas como `superseded` al correr por primera vez
(mismo `activo_key`, distinto `file_hash`), porque la nueva fuente es más
completa y con metodología de NOI correcta. **Pendiente**: si
`actualizar_er_vina` se sigue llamando en el flujo mensual del CDG, va a
volver a insertar filas para `activo_key='Viña Centro'` y re-supersede la
data limpia de este parser — hay que decidir si se desactiva ese dual-write
o se reconcilian ambas fuentes antes de que eso pase.

## Ingesta ER Mall Curicó (activo, fondo TRI)

Fuente: `RAW/NOI Curico.xlsx` (SharePoint), hoja `Hoja1`. Módulo:
`tools/db/ingest_er_curico.py`. `activo_key='Mall Curicó'`.

Mismo enfoque que Viña Centro (código de cuenta por regex, NOI recalculado
desde cuentas crudas), con dos diferencias: no hay header de texto para
arrancar la sección de Ingreso Explotación (arranca por defecto justo
después de la fila de fechas), y el recorrido corta en la **primera**
ocurrencia de "Total Operacional" (la Sección 1 de datos reales está arriba
del archivo, el espejo en UF está abajo — orden inverso a Viña).

**Cuentas huérfanas**: 3 cuentas (`3-1-10-115` Mantención Cobro Directo,
`3-1-10-116` Mantención Activo, `3-1-10-117` Servicios Administrativos
Activo) están físicamente en el bloque de Gastos de Administración y
Ventas, pero las fórmulas `SUM()` de sus subcategorías (MANTENCIÓN,
SERVICIOS) no las incluyen — quedan fuera del NOI oficial de fila 133 de la
fuente. Impacto real hasta 5.7% del gasto en algunos meses. **Confirmado
por el usuario 2026-07-14**: el NOI en la DB las incluye (recalculado desde
las cuentas crudas, no reusa la fórmula de la fuente) — validación de
integridad de Gastos Admin y Ventas es blanda por este motivo (no puede
exigir igualdad exacta contra el subtotal de la fuente).

Sección "Resultado No Operacional" (financiero: leasing, intereses,
variación UF) no se ingesta — no la usa el NOI de referencia.

Rango histórico ingestado: 2023-08 a 2026-05 (34 meses, 1496 filas).

**Nota — reemplaza la ingesta anterior de `actualizar_er_curico`**: existía
una ingesta previa a `raw_er_activo_line` vía `noi_tools.actualizar_er_curico`
(dual-write desde el ER Curicó embebido en el CDG mensual). El `persist()`
de `ingest_er_curico` marcó esas filas como `superseded` al correr por
primera vez (mismo `activo_key`, distinto `file_hash`). **Pendiente**: si
`actualizar_er_curico` se sigue llamando en el flujo mensual del CDG, va a
volver a insertar filas y re-supersede la data limpia de este parser —
mismo pendiente que quedó abierto para Viña.

## Ingesta ER Apoquindo 3001 (fondo TRI)

Fuente: `RAW/NOI 3001.xlsx` (SharePoint), hoja `Hoja1`. Formato categoría×mes
anclado en la fila con label `"Apoquindo 3001"`, header de fechas en la
MISMA fila que la ancla (mismo patrón que Sucden). Módulo:
`tools/db/ingest_er_apo3001.py`.

`activo_key='Apo3001'` fijo (oficina, sociedad Inmobiliaria Chañarcillo
Ltda, participación 0.685 — misma estructura que Sucden). 8 categorías
persistidas: Taipei, Otros, Gastos Comunes, Administración, Comisión
Corredor, Provision Incobrables, Contribuciones + Sobretasa, Seguros.

**Hallazgo — la fila agregada "(+) Ingresos por Arriendos" se descarta**:
la planilla trae esa fila como agregado visual de sus dos sub-detalles
("Taipei" + "Otros"), pero en 2026-03 y 2026-04 el agregado difiere de la
suma de sub-detalles en 0.5 UF (redondeo manual obsoleto en la fuente —
"NOI Mensual" fue calculado con el valor preciso de Taipei+Otros, no con el
agregado). El parser descarta la fila agregada y persiste Taipei/Otros por
separado; con ese criterio la validación de integridad (suma de
componentes == "NOI Mensual") da 0 discrepancias en los 77 periodos
completos (2020-01 a 2026-05, 616 filas = 77 × 8 categorías).

**Nota — coexiste con el feed vía RR JLL**: este activo también recibe NOI
vía `noi_tools.actualizar_noi_apo3001` (hoja "NOI PT" del Rent Roll JLL,
Excel del CDG). No se resolvió si esa ingesta debe deprecarse en favor de
esta — queda igual que el pendiente abierto para Viña/Curicó vs.
`actualizar_er_vina`/`actualizar_er_curico`.

Con Apo3001 quedan consolidados en `raw_er_activo_line` los 5 activos
pendientes del fondo TRI (INMOSA, Sucden, Viña Centro, Curicó, Apo3001).

## Vacancia histórica (DB v2, `memory/agente_toesca_v2.db`, migración 074)

Fuente manual: `RAW/Vacancia histórica DB.xlsx` (SharePoint), 2017-06 a
2026-12, formato activo×mes con dos bloques (m2 GLA y m2 vacantes). Tabla
`raw_vacancia_manual(activo_key, tipo_unidad, periodo, m2_gla, m2_vacantes, ...)`.
Módulo de ingesta: `tools/db/ingest_vacancia_manual.py`.

**Regla**: `raw_rent_roll_line` manda cuando existe para ese activo/período
(más granular — trae `tipo_unidad` por unidad vía `extra_json.tipo_activo_2`);
el archivo manual solo cubre los períodos sin rent roll ingestado. Vistas:

- `v_vacancia_activo_tipo` — activo × período × tipo_unidad (Oficinas /
  Locales Comerciales / Bodegas / Estacionamiento / Otro), con `fuente`
  ('rent_roll' | 'manual')
- `v_vacancia_activo` — colapsa tipo_unidad (excluye Estacionamiento), da `vacancia_pct` total
- `v_vacancia_activo_efectivo` — igual, + `m2_vacantes_efectivo` ponderado por `dim_activo.participacion_fondo_activo`
- `v_vacancia_pt_consolidado_tipo` — Parque Titanium consolidado (Torre A +
  Boulevard) por tipo_unidad; para períodos sin rent roll usa directo el
  pseudo-activo `PT_consolidado` (el archivo fuente no desglosa PT por
  edificio en el histórico, solo por tipo a nivel de todo el complejo)
- `v_vacancia_apoquindo_consolidado_tipo` — Fondo Apoquindo (Apo4501 +
  Apo4700) por tipo_unidad; con rent roll suma ambos activos desglosados
  (Oficinas/Locales/Bodegas/Estacionamiento), sin rent roll usa el desglose
  manual "Fondo Apoquindo Oficinas/Locales" (solo vacancia, sin GLA por tipo)

**tipo_activo_2 vs tipo_activo_1**: en `raw_rent_roll_line.extra_json`,
`tipo_activo_1` queda como literal `"Vacante"` en las unidades vacantes (no
sirve para clasificar el tipo de unidad). `tipo_activo_2` sí es confiable
para vacantes y ocupadas (`Oficina`/`Local`/`Bodega`/`Estacionamiento`) — la
vista usa ese campo.

**Mapeos no obvios** (nombre del archivo → `activo_key`):
- "Chañarcillo" (bloque GLA) = `Sucden` (comparten `sociedad_key`, el
  archivo la llama por el nombre de la sociedad en el bloque GLA pero
  "SUCDEN" en el bloque de vacantes)
- "Fondo Apoquindo" = agregado `Apo4501` + `Apo4700` (confirmado exacto:
  1530.73+1507=3037.73 m2 vacantes 2026-06) — mismo pseudo-activo legacy que
  ya usa `derived_kpi` para NOI/vacancia de Apoquindo, ver
  `docs/matriz-claves-ambiguas-apoquindo.md`
- "Curicó" = `Mall Curicó`, "Apoquindo 3001" = `Apo3001`

## Absorción histórica (DB v2, migraciones 075-076)

No hay rent rolls históricos completos para derivar absorción real. Fuente
manual: `RAW/Absorcion Histórica DB.xlsx` (SharePoint), 3 hojas (`jll`, `viña`,
`curico`), una fila por movimiento de contrato (nuevo/renovó/término) —no es
absorción ya calculada, es el detalle de movimientos crudo. Tabla
`raw_movimiento_contrato(activo_key, tipo_unidad, status, arrendatario, m2,
vencimiento, inicio_nuevo_contrato, ...)`. Módulo de ingesta:
`tools/db/ingest_movimiento_contrato.py`. Ver [[project-absorcion-historica-manual]].

**Mapeo activo** (nombre del archivo → `activo_key`): "Apoquindo 3001"→`Apo3001`,
"Apoquindo 4501"→`Apo4501`, "Apoquindo 4700"→`Apo4700`, "Inm Boulevard PT"→`Boulevard`,
"Torre A"→`Torre A`, "Viña Centro"→`Viña Centro`, "Curicó"→`Mall Curicó`.

**Regla de derivación** (confirmada por el usuario 2026-08-03):
- `status='Nuevo Contrato'` → absorción `+m2`, período = mes de `inicio_nuevo_contrato`
- `status='Término'` → absorción `-m2`, período = mes de `vencimiento`
- `status='Renovó'`/`'Renovación'` → absorción `0` (mismo arrendatario sigue
  ocupando; el archivo no trae m2 antes/después desglosado)
- Excluye `tipo_unidad='Estacionamientos'` (consistente con vacancia)

Vistas: `v_absorcion_movimiento` (detalle por movimiento) y `v_absorcion_activo`
(neto por `activo_key` + `periodo`).

**A futuro**: cuando exista rent roll para todos los períodos, la absorción
debe derivarse de `raw_rent_roll_line` (comparando ocupación mes a mes), igual
que vacancia — este archivo manual queda solo para el histórico sin rent roll.

**Discrepancias detectadas vs. rent roll ya ingestado — resueltas 2026-08-03
con explicación del usuario**:
- **Apo3001 GLA** (4.493,55 manual vs 4.589,55 rent roll): el rent roll
  incluía 80 m2 de estacionamientos. `v_vacancia_activo` ahora excluye
  `tipo_unidad='Estacionamiento'` del total (el parking no es parte del
  universo de vacancia comercial) → GLA 4.509,55 y vacancia 1.632,6 calzan
  exacto contra el manual.
- **Mall Curicó vacancia** (2.476 manual vs 3.017,87 rent roll): explicado
  por la participación del fondo en el activo (0.8). Nueva vista
  `v_vacancia_activo_efectivo` pondera `m2_vacantes` por
  `dim_activo.participacion_fondo_activo` → 3.017,87×0.8=2.414,3, dentro de
  ~2.5% del manual (tolerable, no exacto). La GLA NO se pondera (el archivo
  manual reporta la GLA física completa).
- Torre A/Boulevard: calzan casi exacto sin ajustes (<1% diff).

**Desglose por tipo para Fondo Apoquindo (2026-08-03)**: el usuario agregó a la
misma planilla 2 filas nuevas ("Fondo Apoquindo Oficinas"/"Locales", filas
33-34, solo vacancia, 2019-10 a 2026-06) que reemplazan al total agregado
(fila 26) como fuente vigente desde 2026-06 en adelante — el total agregado no
sigue actualizándose. `v_vacancia_activo` maneja esto con `COALESCE` por
columna (prioriza el total si tiene valor ese periodo, si no suma el
desglose), así que sigue funcionando sin duplicar ni perder datos aunque la
fuente cambie de "total único" a "desglosado" a mitad de historia.
