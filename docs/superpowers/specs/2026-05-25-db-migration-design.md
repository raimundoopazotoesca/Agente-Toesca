# Migración a base de datos para el Automation Agent

**Fecha:** 2026-05-25
**Estado:** Diseño aprobado en brainstorming, pendiente plan de implementación

## 1. Visión y motivación

**Problema actual.** La "base de datos" del agente son planillas Excel gigantes (CDG Mensual: 14 MB, 87 hojas; ER Curicó; ER Viña; NOI-RCSD; RR JLL; etc.). Leer estos archivos es caro en tokens, frágil al parseo y no permite consultas analíticas. La SQLite que ya existe (`memory/agente_toesca.db`) solo guarda historial de chat y contexto — las tablas `kpis` y `contexto` están vacías.

**Visión norte.**

```
HOY:     Proveedor ─► Agente ─► Excel (entregable)
MAÑANA:  Proveedor ─► Agente ─► DB ─┬─► Excel (entregable, mientras se necesite)
                                    └─► Dashboards (consumo directo)
```

- Verdad absoluta: archivos del proveedor (rent rolls, flujos, EERR) y EEFF.
- Excels seguirán existiendo como **entregable**, no como base de datos.
- DB centraliza todo lo que el agente sabe y permite consultas + dashboards.
- Histórico se migra mediante backfill desde las Excels actuales.

**Restricciones.**
- El flujo mensual no puede detenerse durante la migración.
- Cero pérdida de datos. La Excel sigue siendo la entrega "legal" hasta nuevo aviso.
- Reversible en cada paso.

## 2. Arquitectura macro

**Patrón ELT con DB como capa intermedia obligatoria.**

```
Proveedor ──► ingest_* ──► raw_* (DB)
                              │
                              ▼
                         compute_* ──► derived_kpi (DB)
                                            │
                              ┌─────────────┴─────────────┐
                              ▼                           ▼
                         publish_* ─► Excel          query_* ─► agente conversacional / dashboards
```

Reglas:

- **Ninguna tool escribe a Excel sin pasar antes por DB.** Garantiza que DB siempre refleje las planillas.
- Cada tool monolítica actual (`actualizar_noi_pt`, `actualizar_er_curico`, …) se parte en `ingest_*` + `compute_*` + `publish_*`.
- Para preguntas del usuario el agente usa `query_*` (lectura DB). Nunca abre Excel para responder.
- **Idempotencia**: reingestar el mismo archivo del proveedor no duplica filas (clave `(file_hash, source_row)`). Hash distinto marca el anterior `superseded_at`.
- **Linaje**: cada fila raw guarda `source_file`, `source_sheet`, `source_row`, `file_hash`, `loaded_at`. Cada celda derivada guarda `recipe`, `computed_at` y referencia al `ingest_run`.

**Motor: SQLite** (reutilizar `memory/agente_toesca.db`).
- Sin servidor, un archivo, backups triviales, soporta JSON1, suficiente para el volumen esperado (decenas de miles de filas por dominio).
- Descartados: DuckDB (menos maduro en Windows, peor para escrituras transaccionales), Postgres (overkill, requiere servidor).

## 3. Modelo de datos

Cuatro capas. Períodos como `'YYYY-MM'` (ej. `'2026-04'`). Claves textuales legibles, no IDs autonuméricos en dimensiones.

### 3.1 Dimensiones (catálogos estables)

```sql
dim_fondo    (fondo_key PK, nombre, sharepoint_folder)
dim_activo   (activo_key PK, fondo_key FK, nombre, tipo)
dim_serie    (nemotecnico PK, fondo_key FK, serie)
dim_cuenta   (codigo PK, nombre, tipo_eeff, signo)
```

`dim_cuenta` reemplaza los mapeos hardcoded `_NOI_CURICO_MAP` / `_NOI_VINA_MAP`. Cambiar un mapeo deja de requerir tocar código.

### 3.2 Raw (una fila por línea del documento del proveedor)

```sql
raw_rent_roll_line  (id, activo_key, periodo, unidad, arrendatario, m2, renta_uf, vencimiento, …,
                     source_file, source_sheet, source_row, file_hash, loaded_at, ingest_run_id,
                     superseded_at NULL)
raw_flujo_line      (id, activo_key, periodo, cuenta_codigo, monto_clp, monto_uf, …, linaje…)
raw_eeff_line       (id, fondo_key,  periodo, cuenta_codigo, monto_clp, monto_uf, …, linaje…)
raw_er_activo_line  (id, activo_key, periodo, cuenta_codigo, monto_clp, monto_uf, …, linaje…)
```

Constraint único `(file_hash, source_row)`.

### 3.3 Facts (datos directos del mercado, fuente única)

```sql
fact_precio_cuota  (nemotecnico, fecha, precio, fuente)    -- PK (nemotecnico, fecha)
fact_uf            (fecha PK, valor_clp)
fact_dividendo     (nemotecnico, fecha_pago, monto)
```

### 3.4 Derived (todo lo que el agente calcula)

```sql
derived_kpi (
  entidad_tipo,    -- 'fondo' | 'activo' | 'serie'
  entidad_key,     -- fondo_key | activo_key | nemotecnico
  periodo,
  kpi,             -- 'NOI', 'vacancia', 'TIR', 'VR_contable', 'VR_bursatil', 'rentabilidad', …
  valor REAL,
  unidad,
  recipe,          -- versión de la fórmula, ej. 'noi_v1'
  computed_at,
  ingest_run_id    -- de qué corrida de ingesta proviene (FK)
)
```

**Una sola tabla larga**, no una columna por KPI. Esto es lo que permite dashboards y consultas tipo:

```sql
SELECT periodo, kpi, valor
  FROM derived_kpi
 WHERE entidad_key = 'PT' AND kpi IN ('NOI','vacancia')
 ORDER BY periodo;
```

Agregar un KPI nuevo no requiere cambiar schema.

### 3.5 Audit

```sql
ingest_run   (id, tool, source_file, file_hash, rows_in, rows_loaded, started_at, ended_at, status, error)
publish_run  (id, tool, target_excel, target_sheet, periodo, rows_written, started_at, status)
schema_version (version INT PRIMARY KEY, applied_at)
```

## 4. Capa de tools

### 4.1 Cuatro roles

**`ingest_*`** — parser de proveedor → `raw_*`.
- Input: path o URL SharePoint del archivo del proveedor.
- Valida, normaliza unidades, escribe a `raw_*` con linaje y hash.
- Devuelve `ingest_run_id` + resumen (filas leídas, rechazadas, advertencias).
- Ejemplos: `ingest_rent_roll_jll`, `ingest_eeff_pdf`, `ingest_er_vina`, `ingest_er_curico`, `ingest_flujos_inmosa`.

**`compute_*`** — `raw_*` + `fact_*` → `derived_kpi`.
- Aplica receta, escribe con `recipe = 'noi_v1'` (versionado).
- Recomputable: borrar y rehacer no rompe nada.
- Ejemplos: `compute_noi_activo`, `compute_vacancia`, `compute_vr_contable`, `compute_vr_bursatil`, `compute_rentabilidad_serie`, `compute_tir`.

**`publish_*`** — DB → Excel.
- Toma `(entidad, periodo)`, lee de `derived_kpi` / `raw_*`, escribe celdas vía el XML directo ya existente.
- Registra en `publish_run`.
- Ejemplos: `publish_cdg_renta_pt`, `publish_noi_rcsd`, `publish_er_curico`, `publish_factsheet_*`.

**`query_*`** — solo lectura, para el agente conversacional y dashboards.
- `query_kpi(entidad, kpi, desde, hasta)`, `query_serie_temporal(activo, kpi)`, `query_comparar_periodos(...)`, `query_rent_roll(activo, periodo)`, `export_kpis_csv(filtros)`.

### 4.2 Estructura de archivos

```
tools/db/
  schema.py            # DDL versionado
  migrations/
    001_init.sql
    002_*.sql
  repo_fondo.py        # acceso a dim_fondo / dim_activo / dim_serie / dim_cuenta
  repo_rent_roll.py    # acceso a raw_rent_roll_line
  repo_eeff.py
  repo_flujo.py
  repo_er_activo.py
  repo_fact.py         # precios, UF, dividendos
  repo_kpi.py          # derived_kpi
  repo_audit.py        # ingest_run / publish_run
tools/ingest/          # parsers de proveedor
tools/compute/         # cálculo de KPIs
tools/publish/         # escritores a Excel (refactor del código actual)
tools/query/           # endpoints de consulta
```

El resto del agente **nunca escribe SQL crudo**; va siempre por repo.

### 4.3 Orquestación mensual

Comando `cierre_mensual(periodo)`:

```
1. ingest_*   (todos los archivos del mes detectados por convención de nombre)
2. compute_*  (recalcula KPIs que dependen de lo recién ingresado)
3. publish_*  (escribe planillas)
4. validar    (cuadre: NOI publicado == NOI calculado, totales calzan, etc.)
```

Cada paso reporta qué hizo, qué saltó por falta de input, y qué validaciones fallaron. El usuario aprueba al final.

### 4.4 Validaciones automáticas

- **Al publicar:** `valor_excel_post == valor_db` por celda escrita. Si discrepa → abort, log, no commit.
- **Al ingestar:** totales del documento calzan (debe-haber, sumas de subtotales). Filas con anomalías van a una tabla `ingest_warning` (no se rechazan, se marcan).
- **Al computar:** todas las entidades requeridas tienen datos. Si falta input, el KPI no se calcula y se reporta como gap.

## 5. Plan de migración

Estrategia: **dual-write con DB como sombra primero, luego como fuente.** El flujo mensual no se detiene.

### Fase 0 — Esqueleto (1 sesión)
- `tools/db/schema.py` con DDL completo.
- Sistema de migraciones (`schema_version`, archivos `NNN_*.sql`).
- Repos vacíos por dominio con interfaces `insert_*`, `get_*`, `query_*`.
- Seed de `dim_fondo`, `dim_activo`, `dim_serie`, `dim_cuenta` desde los catálogos actuales (hoy hardcoded).
- Tests: schema carga, seeds entran, insert/select básico por repo.
- **Estado**: DB lista, vacía de datos de negocio. Cero impacto en flujo actual.

### Fase 1 — Dual-write por dominio (1 dominio por sesión)
Sin tocar el comportamiento de escritura a Excel, agregar escritura paralela a DB. Orden por valor/riesgo:

1. `fact_precio_cuota` + `fact_uf` — `web_bursatil_tools`. Pequeño, alto reuso.
2. `raw_eeff_line` — `eeff_tools` (PDF). Ya existe el parser.
3. `raw_er_activo_line` (Viña, Curicó) — `noi_tools.actualizar_er_*`.
4. `raw_rent_roll_line` — RR JLL y Tres Asociados.
5. `raw_flujo_line` — INMOSA, Apoquindo, etc.
6. Cómputos derivados (`compute_noi`, `compute_vr_*`, `compute_rentabilidad`).

Por dominio: tests `valor_escrito_excel == valor_en_db`. Si calza → dominio "verificado en dual-write".

### Fase 2 — Backfill histórico (paralelo a Fase 1)
Por cada dominio en dual-write, script `backfill_<dominio>.py`:
- Recorre todas las planillas / PDFs / archivos del proveedor en SharePoint.
- Reusa la misma función `ingest_*` que el flujo en vivo (consistencia).
- Reporta cobertura: `"INMOSA: 2022-01 a 2026-04, 52 meses, 50 ingresados, 2 sin archivo fuente"`.

Costoso en tiempo de ejecución, no de código. Se corre desatendido.

### Fase 3 — Inversión del flujo (cuando un dominio tiene backfill + dual-write verificados)
- Partir la tool en `ingest_*` + `publish_*`. `publish_*` lee DB, no archivo del proveedor.
- Re-correr el mes en curso desde DB y comparar Excel resultante con el de dual-write → idénticos.
- Si calza por 1 mes → dominio DB-first. Si no, debug y repetir.

### Fase 4 — Consulta + dashboards
- Activar `query_*`. System prompt: "Para preguntas sobre datos, usar `query_*`. Solo abrir Excel si la DB no tiene el dato y reportarlo como gap."
- Endpoint `export_kpis_csv(filtros)` / `export_kpis_parquet` para alimentar dashboards externos (Streamlit / Metabase / lo que sea). El dashboard mismo es un proyecto aparte.

### Reversibilidad
- Backup automático del `.db` antes de cada migración de schema y antes de cada backfill (copia con timestamp en `memory/backups/`).
- Cada `ingest_run` se puede deshacer (`DELETE FROM raw_* WHERE ingest_run_id = ?`) sin tocar Excel.
- Hasta Fase 3, Excel sigue siendo la verdad legal → cero riesgo de pérdida.

### Criterio de "listo" por dominio
1. Schema + repo + seed.
2. `ingest_*` dual-write verificado contra Excel ≥ 1 mes.
3. Backfill histórico con cobertura ≥ 95% (gaps documentados).
4. `compute_*` produce los mismos números que las fórmulas Excel.
5. `publish_*` re-genera la celda Excel desde DB con `valor_excel == valor_db`.
6. `query_*` expuesto y agente lo usa por defecto.

## 6. Decisiones clave

| Decisión | Elegido | Alternativa descartada |
|---|---|---|
| Motor DB | SQLite (reusar el existente) | DuckDB, Postgres |
| Modelo de KPIs | Tabla larga `derived_kpi` | Columna por KPI |
| Identificadores | Claves textuales legibles | IDs autonuméricos |
| Períodos | `'YYYY-MM'` string | DATE, INT, FK a dim_periodo |
| Plan de cuentas | `dim_cuenta` central | Mapeos hardcoded en código |
| Idempotencia | `(file_hash, source_row)` único | Borrar/reinsertar por periodo |
| Flujo de migración | Dual-write → backfill → invertir | Big-bang con freeze |
| Excel como entregable | Sí, mientras lo pidan | Eliminar Excel ya |

## 7. Fuera de alcance de este spec

- La implementación del dashboard (Streamlit / Metabase / etc.) — proyecto aparte una vez `query_*` y `export_*` estén disponibles.
- Multi-usuario / autenticación de la DB — sigue siendo single-user local.
- Migración a Postgres / cloud — sólo si SQLite deja de ser suficiente; señales: corrupción concurrente o > 1 GB.
- Versionado bitemporal completo (válido-en + grabado-en) — por ahora basta con `superseded_at`. Si se necesita auditoría histórica más fina, agregar después.
