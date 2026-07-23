# Consolidación Parking Parque Titanium (SABA) — Design

**Fecha:** 2026-07-23
**Estado:** aprobado (secciones 1 y 2). Sección 3 (UI de ingesta) postergada hasta definir archivo estándar.

## Contexto

El parking del Parque Titanium está administrado por SABA. Existe una planilla histórica
(`SharePoint > raw > Parking PT DB.xlsx`) con:

- **Hoja `Tickets`**: 1 fila por día desde 2023-01-01. Cols: fecha, día_semana, mes,
  año, día_mes, tickets, feriado_flag. Datos hasta abr-2027 (futuro vacío).
- **Hoja `Ingresos`** (matriz): filas = concepto, cols = mes desde ene-2023.
  - UF de cierre por mes (ignorar, ya está en `raw_uf_diaria`)
  - Ventas (~7 conceptos con código de cuenta: 70500000-254, 70500001-256,
    70500002-261, 70500003-250, algunos con signo `-` para notas de crédito)
  - Gastos (~11 conceptos con código proveedor: 363, 200, 253)
  - Totales derivados (Total Ingresos Mensual, Total Gastos)
  - Facturación SABA (Neto/IVA/Bruto) y Liquidación factura (Neto/IVA/Bruto)
  - Pago a Parque Titanium (derivado)

**Objetivo de esta iteración:** consolidar el histórico en la DB con un modelo
escalable, dejando lista la infra para futuras ingestas periódicas.

## Sección 1 — Esquema de tablas (aprobado)

### `dim_concepto_parking`

Catálogo de conceptos de ingreso/gasto de SABA. Similar a `dim_cuenta_eeff` pero
para el dominio parking.

```sql
CREATE TABLE dim_concepto_parking (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo      TEXT,                    -- '70500000-254', '363', '200', '253'
  nombre      TEXT NOT NULL,           -- 'Ingresos Efectivos (Neto)', 'MANTENCION SKYDATA', ...
  tipo        TEXT NOT NULL,           -- 'venta' | 'gasto'
  signo       INTEGER NOT NULL DEFAULT 1,   -- +1 | -1 (aplicado al persistir)
  descripcion TEXT,
  activo      INTEGER NOT NULL DEFAULT 1,
  UNIQUE(codigo, nombre, signo)
);
```

Se seedan al aplicar la migración con los ~18 conceptos actuales.

### `raw_parking_ingreso_line`, `raw_parking_gasto_line`

Una fila por (activo, periodo, concepto). Estructura idéntica en las dos.

```sql
CREATE TABLE raw_parking_ingreso_line (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_id      INTEGER NOT NULL REFERENCES dim_activo(id),
  periodo        TEXT NOT NULL,        -- 'YYYY-MM'
  concepto_id    INTEGER NOT NULL REFERENCES dim_concepto_parking(id),
  monto_clp      REAL NOT NULL,        -- signo ya aplicado
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT,
  UNIQUE(activo_id, periodo, concepto_id, superseded_at)
);
```

`raw_parking_gasto_line` es idéntica.

### `raw_parking_ticket_line`

Una fila por (activo, día).

```sql
CREATE TABLE raw_parking_ticket_line (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_id      INTEGER NOT NULL REFERENCES dim_activo(id),
  fecha          TEXT NOT NULL,        -- 'YYYY-MM-DD'
  tickets        INTEGER NOT NULL,
  feriado        INTEGER NOT NULL DEFAULT 0,   -- 0/1
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT,
  UNIQUE(activo_id, fecha, superseded_at)
);
```

### `raw_parking_facturacion_line`

Outputs mensuales del proceso SABA (facturación + liquidación + pago).
Separada del detalle de ingresos/gastos porque son *agregados* del proceso, no
líneas de detalle.

```sql
CREATE TABLE raw_parking_facturacion_line (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_id      INTEGER NOT NULL REFERENCES dim_activo(id),
  periodo        TEXT NOT NULL,
  concepto       TEXT NOT NULL,   -- 'saba_neto' | 'saba_iva' | 'saba_bruto'
                                  -- 'liquidacion_neto' | 'liquidacion_iva' | 'liquidacion_bruto'
                                  -- 'pago_a_pt'
  monto_clp      REAL NOT NULL,
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT,
  UNIQUE(activo_id, periodo, concepto, superseded_at)
);
```

### Vista `v_parking_mensual`

Consumo simplificado (una fila por activo × periodo con agregados).

```sql
CREATE VIEW v_parking_mensual AS
SELECT
  i.activo_id,
  i.periodo,
  SUM(CASE WHEN c.tipo='venta' THEN i.monto_clp END) AS ingresos_totales_clp,
  (SELECT SUM(g.monto_clp)
     FROM raw_parking_gasto_line g
     JOIN dim_concepto_parking cg ON cg.id = g.concepto_id
    WHERE g.activo_id=i.activo_id AND g.periodo=i.periodo
      AND g.superseded_at IS NULL) AS gastos_totales_clp
FROM raw_parking_ingreso_line i
JOIN dim_concepto_parking c ON c.id = i.concepto_id
WHERE i.superseded_at IS NULL
GROUP BY i.activo_id, i.periodo;
```

### Convenciones aplicadas (del proyecto)

- `periodo` string `'YYYY-MM'`
- `loaded_at` `'YYYY-MM-DD HH:MM:SS'` (DEFAULT `datetime('now')`)
- Todas las tablas raw versionadas con `superseded_at IS NULL` como filtro vigente
- Idempotencia vía `file_hash` (mismo hash → aborta el script)

**No se persisten:** UF Cierre (ya en `raw_uf_diaria`), Total Ingresos Mensual,
Total Gastos (derivables con SUM sobre el detalle).

## Sección 2 — Consolidación histórica + integración (aprobado)

### A. Migración `migrations/050_parking_pt.sql`

- CREATE de las 4 tablas + vista
- INSERT semilla de `dim_concepto_parking` con los ~18 conceptos leídos de la
  planilla actual (código, nombre, tipo, signo)

### B. Script one-shot `scripts/ingest_parking_pt_historico.py`

Lógica adhoc, no reusable — está diseñado para leer *esta* planilla:

1. Copia archivo a scratchpad (evita `PermissionError` de OneDrive).
2. Calcula `file_hash` del original. Si existe fila con ese hash en cualquiera
   de las 4 tablas raw → aborta con mensaje explícito.
3. Crea nuevo `ingest_run`.
4. Hoja `Ingresos`:
   - Detecta fila 3 cols D+ → mapa `columna → periodo YYYY-MM`.
   - Filas 5-11 (ventas) y 14-26 (gastos): lee `(codigo, signo, nombre)` de
     cols A/B/C. Match/insert en `dim_concepto_parking`. Para cada columna con
     monto, insert en `raw_parking_ingreso_line` o `raw_parking_gasto_line`
     (con signo ya aplicado).
   - Filas 29-31 y 33-37 → `raw_parking_facturacion_line`
     (concepto ∈ {saba_neto, saba_iva, saba_bruto, liquidacion_neto,
     liquidacion_iva, liquidacion_bruto, pago_a_pt}).
5. Hoja `Tickets`: filtra filas con `tickets IS NOT NULL` (salta futuro vacío).
   Insert en `raw_parking_ticket_line`.
6. Todo dentro de una única transacción.
7. `verify_parking_ingest()` (función en el mismo script, reusable):
   - Para cada mes: `SUM(raw_parking_ingreso_line.monto_clp)` == "Total
     Ingresos Mensual" (fila 13 de la planilla). Tolerancia ±1 CLP.
   - Idem gastos vs fila 27.
   - Tickets: por año, `COUNT(*) == días con dato en planilla`.
   - Nulls en concepto o periodo == 0.
   - Print `OK` / `MISMATCH periodo=... esperado=... obtenido=...`.

### C. Integración con NOI PT — decisión: no cruzar en esta iteración

El NOI PT actual (fuente RR JLL → `raw_er_activo_line`) ya contabiliza el
ingreso del parking a nivel agregado. Cruzar el detalle SABA duplicaría. Las
tablas parking quedan como **fuente independiente** para análisis (evolución
tickets, márgenes SABA, estacionalidad, gasto por concepto).

Cuando se decida migrar el NOI del parking a fuente SABA, será una sesión
separada con vista `v_parking_a_er` que emita filas hacia `raw_er_activo_line`
marcadas con `source='parking_saba'`.

### D. Verificación (obligatoria post-consolidación)

Ejecutar `verify_parking_ingest()` y confirmar que todos los checks pasan
antes de dar el trabajo por completo.

## Sección 3 — UI de ingesta (postergada)

Se define en sesión futura cuando esté claro cuál será el archivo estándar
mensual que enviará SABA (¿mismo formato de esta planilla completa?, ¿un
recorte mensual?, ¿otro layout?). Recién ahí tiene sentido diseñar el tab en
`web/ingesta.html`.

## Fuera de scope

- Ingesta periódica automatizada (viene en sección 3, futuro).
- Persistir totales/derivadas — se calculan al consultar.
- Integración con NOI (viene en su propia sesión).
- Análisis de estacionalidad, forecasting — capa de dashboard, no de ingesta.
