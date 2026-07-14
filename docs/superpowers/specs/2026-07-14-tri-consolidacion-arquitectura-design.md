# Consolidación fondo TRI — arquitectura DB

**Fecha**: 2026-07-14
**Contexto**: Ya se consolidaron ingresos/NOI de PT (Torre A + Boulevard) y Apo (Apo4501 + Apo4700). Faltan los activos restantes del fondo paraguas TRI: INMOSA, Sucden, Viña Centro, Mall Curicó, Apoquindo 3001. Además PT y Apo son subfondos de TRI (33.3% y 30% respectivamente), por lo que su NOI también rolla hacia TRI vía look-through.

## Objetivo

Diseñar la arquitectura de DB que permita:
1. Ingestar ingresos y NOI de los 5 activos pendientes reutilizando el patrón `raw_er_activo_line` de PT/Apo.
2. Consolidar NOI/Ingresos a nivel fondo TRI incluyendo activos directos + subfondos (PT, Apo).
3. Preservar las 3 capas de participación del organigrama (activo↔sociedad, sociedad↔fondo, fondo↔fondo) sin colapsarlas.

## Organigrama (fuente de verdad)

TRI (Toesca Rentas Inmobiliarias Fondo de Inversión) tiene:

| Sociedad / Subfondo | % TRI | Activo(s) | % activo en sociedad |
|---|---|---|---|
| Inmobiliaria Chañarcillo Ltda | 100% | Sucden | 100% |
| Inmobiliaria Chañarcillo Ltda | 100% | Apoquindo 3001 | **68.5%** |
| Inmobiliaria VC SpA → Viña Centro SpA | 100% | Mall Paseo Viña Centro | 100% |
| Power Center Curicó SpA | **80%** | Power Center Paseo Curicó | 100% |
| Inmob. e Inv. Senior Assist Chile S.A. | **43%** | 6 Residencias Adulto Mayor (agregadas como INMOSA) | 100% |
| Fondo Toesca Rentas Inmobiliarias PT (subfondo) | **33.3%** | Torre A, Boulevard | 100% |
| Fondo Toesca Rentas Inmob Apoquindo (subfondo) | **30%** | Apo4501, Apo4700 | 100% |

## Estado actual de la DB

Tabla `dim_activo` tiene una columna `participacion_fondo_activo` con **semánticas mezcladas**:
- Apo4501/Apo4700 = 1.0 (participación directa Apo→activo, semántica correcta)
- Torre A/Boulevard = 0.333 (look-through TRI, semánticamente en el fondo equivocado)
- INMOSA = 0.43, Viña = 1.0, Sucden = 1.0, Curicó = 0.80, Apo3001 = 1.0 (mezcla — Apo3001 está mal, debería reflejar 68.5%)

`dim_fondo` no tiene concepto de subfondo/padre.

Consumidor crítico de la columna vieja: **`tools/noi_query.py`** (ponderación NOI). Además tiene `_SPLIT_PART = {"PT Torre A": 0.333, "PT Boulevard": 0.333}` hardcodeado que replica los valores actuales. Test relacionado: `tests/db/test_ingest_er_apoquindo.py`.

## Diseño

### Principio guía: aditivo puro, cero cambios destructivos

Ningún valor existente cambia, ninguna columna vieja se renombra ni elimina. Los consumidores actuales siguen funcionando exactamente igual. Se agrega estructura nueva que convive con la vieja hasta que se migre en Fase 2.

### Schema nuevo (migración 049)

```sql
-- ── 1. Sociedades / holdings intermedias ──
CREATE TABLE dim_sociedad (
  sociedad_key TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  fondo_key TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
  participacion_fondo_en_sociedad REAL NOT NULL  -- % del fondo dueño en esta sociedad
);

-- Datos:
-- ('Chanarcillo',   'Inmobiliaria Chañarcillo Ltda',                       'TRI', 1.0)
-- ('CuricoSpA',     'Power Center Curicó SpA',                             'TRI', 0.80)
-- ('SeniorAssist',  'Inmob. e Inv. Senior Assist Chile S.A.',              'TRI', 0.43)
-- ('VCSpA',         'Inmobiliaria VC SpA / Viña Centro SpA (colapsada)',   'TRI', 1.0)
-- ('TorreASA',      'Torre A S.A.',                                        'PT',  1.0)
-- ('BlvdSpA',       'Inmobiliaria Boulevard PT SpA',                       'PT',  1.0)
-- ('ApoquindoSpA',  'Inmobiliaria Apoquindo SpA',                          'Apo', 1.0)

-- ── 2. Activo ↔ sociedad (nueva relación) ──
ALTER TABLE dim_activo ADD COLUMN sociedad_key TEXT REFERENCES dim_sociedad(sociedad_key);
ALTER TABLE dim_activo ADD COLUMN participacion_en_sociedad REAL;

-- Poblado:
-- Sucden          → sociedad='Chanarcillo',    participacion_en_sociedad=1.0
-- Apo3001         → sociedad='Chanarcillo',    participacion_en_sociedad=0.685
-- Viña Centro     → sociedad='VCSpA',          participacion_en_sociedad=1.0
-- Mall Curicó     → sociedad='CuricoSpA',      participacion_en_sociedad=1.0
-- INMOSA          → sociedad='SeniorAssist',   participacion_en_sociedad=1.0
-- Torre A         → sociedad='TorreASA',       participacion_en_sociedad=1.0
-- Boulevard       → sociedad='BlvdSpA',        participacion_en_sociedad=1.0
-- Apo4501         → sociedad='ApoquindoSpA',   participacion_en_sociedad=1.0
-- Apo4700         → sociedad='ApoquindoSpA',   participacion_en_sociedad=1.0
-- (residencias legacy, Guardiamarina, Placilla → NULL; se limpian después)

-- ── 3. Subfondos ──
ALTER TABLE dim_fondo ADD COLUMN fondo_padre TEXT REFERENCES dim_fondo(fondo_key);
ALTER TABLE dim_fondo ADD COLUMN participacion_en_padre REAL;
-- UPDATE dim_fondo SET fondo_padre='TRI', participacion_en_padre=0.333 WHERE fondo_key='PT';
-- UPDATE dim_fondo SET fondo_padre='TRI', participacion_en_padre=0.30  WHERE fondo_key='Apo';

-- ── 4. Vista de look-through efectivo ──
CREATE VIEW v_activo_fondo_efectivo AS
  -- fila directa (fondo dueño de la sociedad)
  SELECT
    a.activo_key,
    s.fondo_key AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad AS participacion_efectiva,
    'directa' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  WHERE a.sociedad_key IS NOT NULL
  UNION ALL
  -- fila look-through hacia el fondo padre
  SELECT
    a.activo_key,
    f.fondo_padre AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad * f.participacion_en_padre AS participacion_efectiva,
    'lookthrough' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  JOIN dim_fondo   f ON s.fondo_key    = f.fondo_key
  WHERE a.sociedad_key IS NOT NULL AND f.fondo_padre IS NOT NULL;
```

### Resultado esperado de `v_activo_fondo_efectivo`

| activo_key | fondo_key | participacion_efectiva | via |
|---|---|---|---|
| Sucden | TRI | 1.000 | directa |
| Apo3001 | TRI | 0.685 | directa |
| Viña Centro | TRI | 1.000 | directa |
| Mall Curicó | TRI | 0.800 | directa |
| INMOSA | TRI | 0.430 | directa |
| Torre A | PT | 1.000 | directa |
| Boulevard | PT | 1.000 | directa |
| Apo4501 | Apo | 1.000 | directa |
| Apo4700 | Apo | 1.000 | directa |
| Torre A | TRI | 0.333 | lookthrough |
| Boulevard | TRI | 0.333 | lookthrough |
| Apo4501 | TRI | 0.300 | lookthrough |
| Apo4700 | TRI | 0.300 | lookthrough |

### Ingesta ER de los 5 activos pendientes

Reutiliza el patrón existente (`tools/db/ingest_er_pt.py`, `tools/db/ingest_er_apoquindo.py`):

- Un módulo `tools/db/ingest_er_<activo>.py` por planilla fuente
- Persiste líneas en `raw_er_activo_line` con `activo_key`, `periodo`, `cuenta_codigo`, `seccion` (`INGRESOS_OPERACION` / `GASTOS_OPERACION`), `es_operacional`, `monto_clp`
- Idempotente por `file_hash`
- NOI **no se persiste** — se deriva como `SUM(monto_clp) WHERE es_operacional=1`

El activo_key ya existe en `dim_activo` para los 5 casos. No hay sub-activos: cada planilla nueva viene agregada por activo (confirmado por el usuario para INMOSA; se asume igual para el resto hasta que se demuestre lo contrario).

### Consolidación de NOI/Ingresos por fondo

Query canónica para NOI mensual del fondo TRI (o cualquier fondo):

```sql
SELECT
  r.periodo,
  SUM(r.monto_clp * v.participacion_efectiva) AS noi_ponderado,
  SUM(r.monto_clp)                            AS noi_100pct
FROM raw_er_activo_line r
JOIN v_activo_fondo_efectivo v ON r.activo_key = v.activo_key
WHERE v.fondo_key = 'TRI'
  AND r.es_operacional = 1
  AND r.superseded_at IS NULL
GROUP BY r.periodo
ORDER BY r.periodo;
```

Se entregan las dos vistas (`noi_100pct` y `noi_ponderado`) en la misma query — el consumidor elige. `derived_kpi` puede cachear ambas si se necesita rendimiento.

## Impacto en consumidores existentes

| Consumidor | Impacto | Acción |
|---|---|---|
| `tools/noi_query.py` | Ninguno — sigue leyendo `dim_activo.participacion_fondo_activo` cuyos valores no cambian | Sin cambios en Fase 1 |
| `tests/db/test_ingest_er_apoquindo.py` | Ninguno — seed usa columna vieja | Sin cambios |
| `tools/db/repo_fondo.py` | Ninguno — filtra por `fondo_key` directo | Sin cambios |
| `dashboards/eeff_tri.py` | Ninguno | Sin cambios |
| Consumidores nuevos (consolidación TRI) | Usan `v_activo_fondo_efectivo` | Nuevo código |

## Guardas de no-regresión

Antes de aplicar la migración en producción:
1. **Backup**: copiar `memory/agente_toesca_v2.db` a `memory/backups/agente_toesca_v2.YYYYMMDD-HHMM.db`.
2. **Transacción**: migración envuelta en `BEGIN`/`COMMIT`. Si falla, rollback total.
3. **Tests pass**: `pytest tests/db/` completo antes y después.
4. **Sanity queries manuales**:
   - `SELECT COUNT(*) FROM v_activo_fondo_efectivo` = 13 (9 directas + 4 lookthrough)
   - Los 5 activos pendientes (INMOSA, Sucden, Viña, Curicó, Apo3001) aparecen en la vista con fondo='TRI' y % correcto
   - `noi_query.serie_mensual(nivel='fondo', clave='PT', ponderado=True)` da los mismos valores que antes de la migración (comparación con snapshot previo)

## Roadmap por fases

**Fase 1 (este spec)** — migración aditiva 049 + vista + poblado. Sin tocar consumidores. Sale este spec + plan de implementación separado.

**Fase 2 (sesiones futuras)** — a medida que se ingesten los 5 activos pendientes uno por uno, cada uno con su propio spec/plan (INMOSA primero). El schema de esta Fase 1 los soporta a todos sin cambios adicionales.

**Fase 3 (deuda técnica, fuera de scope)** — migrar `noi_query.py` a `v_activo_fondo_efectivo`, eliminar `_SPLIT_PART` hardcoded, deprecar `dim_activo.participacion_fondo_activo`, limpiar residencias legacy y Guardiamarina/Placilla (otro fondo, misplaced).

## Fuera de scope

- Ingesta de las planillas de los 5 activos (spec/plan aparte por activo cuando el usuario entregue las planillas).
- Reasignación de Guardiamarina/Placilla al fondo correcto (otro fondo aún no modelado).
- Limpieza de las 6 residencias individuales que hoy están en `dim_activo` — se ingestará INMOSA agregado.
- Migración de `noi_query.py` a la vista nueva.
