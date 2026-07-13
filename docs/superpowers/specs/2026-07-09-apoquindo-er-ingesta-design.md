# Ingesta ER Fondo Apoquindo (Apo4501, Apo4700) — Diseño

**Fecha:** 2026-07-09
**Estado:** Draft — pendiente aprobación del usuario
**Motivación:** Mientras no llegan las respuestas de las APIs de JLL y Tres Asociados, poblar la DB con los datos de ingresos y NOI que tenemos localmente para el fondo Apoquindo, empezando por los activos 4501 y 4700.

## Objetivo

Persistir en `agente_toesca_v2.db` las líneas mensuales de estado de resultado por activo (Apo4501 y Apo4700) leídas desde una planilla local en formato "resumen por categoría", y habilitar el cálculo de **NOI mensual por activo** y su consolidación al **fondo Apo**.

## Alcance

- **In-scope:** ER mensual histórico completo que traiga la planilla, para Apo4501 y Apo4700, granularidad de categoría (10 conceptos).
- **In-scope:** Corrección del bug de `dim_activo.participacion_fondo_activo` para Apo4501 y Apo4700 (hoy 0.3, debe ser 1.0).
- **Out-of-scope:** NOI del fondo TRI consolidado (la relación TRI→Apo=0.3 ya vive fuera de `dim_activo` y no se toca aquí).
- **Out-of-scope:** UI/dashboard (viene después, contra la misma tabla).
- **Out-of-scope:** Persistir el NOI como fila — se calcula on-demand.
- **Out-of-scope (plan futuro):** Proyección de contribuciones para meses sin dato en la planilla. Fórmula acordada 2026-07-09 (dejada aquí para no perderla):
  - Contribución total mensual CLP = `(-165.941.575 - 62.167.695) / 3` = `-76.036.423,33` CLP/mes
  - En UF: `total_uf = total_clp / UF_mes` (leer UF de `fact_uf`)
  - Reparto: **Apo4700 = 25%**, **Apo4501 = 75%** del total
  - Sólo aplica a meses que **no tienen** fila `APO_CONTRIB` cargada desde la planilla histórica.

## Decisiones de diseño

### D1 — Reutilizar `raw_er_activo_line`, no crear tabla nueva

La tabla ya existe y ya la usan Viña Centro y Mall Curicó. Acepta `cuenta_codigo = NULL` en el schema. Un solo modelo de ER por activo simplifica queries downstream (`SUM(monto_clp) WHERE es_operacional=1 GROUP BY activo_key, periodo`) y permite que fuentes futuras (API JLL con cuenta contable) coexistan con la planilla local: filtrar por `source_file` o por presencia/ausencia de `cuenta_codigo`.

### D2 — Granularidad = categoría, con pseudo-código estable

La planilla viene resumida en 10 categorías por activo. Cada una se persiste como una fila en `raw_er_activo_line` con:

| categoría planilla | `cuenta_codigo` | `seccion` | `es_operacional` |
|---|---|---|---|
| Ingresos por Arriendos | `APO_ING_ARR` | `INGRESOS_OPERACION` | 1 |
| Gastos Comunes/Vacancia | `APO_GC_VAC` | `GASTOS_OPERACION` | 1 |
| Comisión Corredor | `APO_COM_CORR` | `GASTOS_OPERACION` | 1 |
| Administración | `APO_ADM` | `GASTOS_OPERACION` | 1 |
| Provisión Reparaciones | `APO_PROV_REP` | `GASTOS_OPERACION` | 1 |
| Gastos Bono+Legales+Otros | `APO_BONOS_LEG` | `GASTOS_OPERACION` | 1 |
| Gastos Constructores Asociados | `APO_CONSTRUCT` | `GASTOS_OPERACION` | 1 |
| Gastos IVA no recuperado + Otros | `APO_IVA_NR` | `GASTOS_OPERACION` | 1 |
| Contribuciones | `APO_CONTRIB` | `GASTOS_OPERACION` | 1 |
| Seguros | `APO_SEG` | `GASTOS_OPERACION` | 1 |

`cuenta_nombre` guarda la etiqueta humana ("Ingresos por Arriendos", etc.). Los pseudo-códigos permiten queries determinísticas sin depender del string libre.

**Por qué pseudo-códigos y no `NULL`:** hace las queries de composición NOI reproducibles (`WHERE cuenta_codigo = 'APO_ING_ARR'`) y permite mapear más tarde a cuentas contables reales cuando llegue el detalle de JLL, sin re-escribir consultas.

### D3 — Signo contable ya aplicado en `monto_clp`

Consistente con `raw_eeff_line`: ingresos positivos, gastos negativos. La planilla ya viene así ("(-) Gastos..." con montos negativos). El ingestor lee y persiste literal. Consumidores hacen `SUM(monto_clp)` sin ramificar signos.

### D4 — NOI derivado, no persistido

La fila "NOI Mensual" de la planilla **no se ingesta**. Se recalcula:

```sql
SELECT activo_key, periodo, SUM(monto_clp) AS noi_clp
FROM raw_er_activo_line
WHERE es_operacional = 1 AND superseded_at IS NULL
GROUP BY activo_key, periodo
```

Si el uso repetido lo justifica más adelante, cachear en `derived_kpi` con `entidad_tipo='activo'`, `kpi='noi_mensual'`, `variante='mes'`, siguiendo el patrón de smart-caching descrito en la skill `real-estate-finance-expert`.

Consolidación al fondo Apo: `SUM(noi_activo * dim_activo.participacion_fondo_activo)` con `fondo_key='Apo'`. Tras el fix de D6, ambos activos suman 1.0 → NOI fondo Apo = NOI 4501 + NOI 4700.

### D5 — Idempotencia por `file_hash`

Mismo patrón que Curicó/Viña:

1. Calcular `file_hash` (SHA-256 del xlsx completo)
2. Si ya existe una `ingest_run` con ese hash → skip
3. Si no, borrar/superseder filas previas del mismo `(activo_key, periodo)` cargadas por corridas anteriores de este ingestor y hacer INSERT limpio, o marcar `superseded_at = datetime('now')` en las viejas antes de insertar las nuevas

Estrategia elegida: **`superseded_at` en filas viejas + INSERT nuevas**. Preserva historial de correcciones y es coherente con el resto del schema. Queries siempre filtran `WHERE superseded_at IS NULL`.

### D6 — Fix `dim_activo.participacion_fondo_activo`

Cambio puntual dentro del mismo PR, con test/verificación:

```sql
UPDATE dim_activo SET participacion_fondo_activo = 1.0
WHERE activo_key IN ('Apo4501','Apo4700');
```

Justificación: el fondo Apo es dueño 100% de ambos activos. El 30% es la relación **fondo TRI → fondo Apo**, que es fondo-fondo, no fondo-activo, y se modela en otro lado. Si algún consumidor actual ya asumía el 0.3, hay que localizarlo (grep `Apo4501|Apo4700` + `participacion`) antes de mergear.

## Componentes

### Nuevo script: `tools/db/ingest_er_apoquindo.py`

Responsabilidades acotadas:

1. Leer el xlsx con openpyxl (una hoja, formato de la imagen)
2. Detectar el header con la fila de meses (`dic-24, ene-25, ...`) → mapear a `periodo = YYYY-MM`
3. Localizar cada bloque de categoría y sus dos sub-filas de activo (4700, 4501) — mapeo por keyword en col A
4. Emitir un iterable de `dict` (una fila por `activo × periodo × categoría`) con los campos ya normalizados
5. Insertar via SQL directo con la lógica de `superseded_at` descrita en D5 (si al implementar se ve que la lógica se repetiría con otros ingestors de ER, extraer a `tools/db/repo_er.py`; en primera iteración vive dentro del propio script)
6. Registrar `ingest_run` con `file_hash`, `source_file`, `rows_inserted`, `activos_afectados`

CLI: `python -m tools.db.ingest_er_apoquindo path/al/archivo.xlsx [--dry-run]`

`--dry-run` imprime el DataFrame que ingresaría sin escribir. Requerido para validar antes de escribir en producción.

### Tests: `tests/db/test_ingest_er_apoquindo.py`

- Fixture con un xlsx minimalista (3 meses × 2 activos × 10 categorías) construido en `setUp` con openpyxl
- Test 1: primera corrida inserta 3×2×10 = 60 filas, todas con `superseded_at IS NULL`
- Test 2: segunda corrida con el mismo `file_hash` es idempotente (no duplica, no supersede)
- Test 3: segunda corrida con hash distinto marca las viejas como superseded y crea nuevas
- Test 4: NOI recalculado con `SUM(monto_clp) WHERE es_operacional=1` coincide con la fila "NOI Mensual" de la planilla dentro de tolerancia (redondeo M$)
- Test 5: signos correctos — ingresos > 0, gastos < 0

### Migración de datos: fix `dim_activo`

Un archivo SQL puntual en `tools/db/migrations/` (siguiente número disponible) o un script inline en el ingestor la primera vez que corre. Preferencia: **migración SQL versionada** — no ata el fix a la ejecución del ingestor.

## Flujo de datos

```
planilla.xlsx
      │
      ▼
ingest_er_apoquindo.py
      │  ├─ file_hash
      │  ├─ parse (openpyxl)
      │  └─ normalize → filas (activo_key, periodo, cuenta_codigo, monto_clp, ...)
      ▼
raw_er_activo_line     +    ingest_run (audit)
      │
      ▼ (query on-demand)
NOI activo mensual  ─── * participacion_fondo_activo ──►  NOI fondo Apo
      │
      ▼ (si vale la pena cachear)
derived_kpi
```

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Formato de la planilla cambia (columnas se mueven) | Parser localiza header por texto ("dic-24" pattern) + categorías por keyword en col A, no por índice fijo. Test con fixture. |
| Doble contabilización si se ingesta la misma planilla dos veces con distinto nombre | `file_hash` es sobre contenido; nombres distintos con mismo contenido → skip idempotente |
| Signos invertidos en la planilla (imagen muestra "-155" para gastos, ok) | Test 5 explícito |
| Consumidores existentes usan `participacion_fondo_activo=0.3` de Apo4501/4700 | Grep antes de mergear; documentar el cambio en `wiki/log.md` |
| Filas de sub-totales dentro de la planilla se ingieren como categoría | Whitelist estricto de 10 categorías; cualquier fila fuera del set se ignora con warning |

## Verificación

Antes de dar por completado:

1. `python -m tools.db.ingest_er_apoquindo <planilla> --dry-run` muestra las filas esperadas
2. Corrida real → `SELECT COUNT(*) FROM raw_er_activo_line WHERE activo_key IN ('Apo4501','Apo4700')` = N meses × 2 activos × 10 categorías
3. NOI del último mes de la planilla, calculado por SQL, coincide con la fila "NOI Mensual" de la planilla ±M$1
4. `SELECT participacion_fondo_activo FROM dim_activo WHERE activo_key IN ('Apo4501','Apo4700')` devuelve 1.0 y 1.0
5. Tests unitarios verdes
6. Wiki actualizada (log + página fondo Apo)
