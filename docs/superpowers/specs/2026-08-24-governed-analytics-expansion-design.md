# Governed Analytics Expansion v1 — Design

Fecha: 2026-08-24
Rama: `feat/alpha-v0.1`
Antecedente: "Alpha Functional Recovery v1" (baseline 5 PASS / 4 PARTIAL / 6 FAIL → recovery 7 / 1 / 7).

## 1. Problema

La ruta gobernada (Metric Catalog → `AnalyticsExecutor` → `ToolEvidence` →
guards 5.3/5.4) sólo cubre vacancia: `vacancia_pct_fondo`,
`vacancia_fisica_pct_activo`, `m2_vacantes`. LTV y NOI existen en
`derived_kpi` pero **no tienen capability gobernada**, así que las preguntas
sobre ellos caen a `run_sql`, y los guards 5.3/5.4 —correctamente— cierran en
falso porque no hay autoridad canónica detrás de ese SQL.

Adicionalmente hay tres defectos estructurales detectados:

- **D1 — escala de unidades.** `ltv` en `derived_kpi` es un ratio crudo
  (0.7115…), mientras `vacancia_pct` ya viene en escala porcentual (5.945 =
  5.945 %). No existe forma de expresar esa diferencia en el catálogo.
- **D2 — evidencia multi-fila escalar se descarta.** En
  `_AnalyticsCapabilityAction.execute`, `result_kind=="scalar"` con
  `len(rows)>1` (una serie temporal) cae al `else` implícito y produce
  `evidence=None`: la evidencia se pierde en silencio (bug del caso 08).
- **D3 — colapso por entidad en el binding gobernado.** `coverage_guard`
  indexa hechos con `fact_by_entity = {fact["entity_id"]: fact}`. Con varias
  filas de la misma entidad en distintos períodos, todas menos una se pierden
  y el claim puede quedar ligado a un período incorrecto.

## 2. Alcance

Se expande la ruta gobernada a LTV, NOI, ranking/breakdown con subconjuntos y
enumeración de entidades, **sin** debilitar guards, **sin** lógica específica
por métrica fuera del catálogo, y **sin** migraciones de base de datos (la DB
se trata como sólo-lectura para este trabajo).

## 3. Auditoría fresca (2026-08-24)

`SELECT DISTINCT entidad_tipo, kpi, variante, formula FROM derived_kpi` para
kpi que contengan `ltv`/`noi`:

```
('activo','ltv',None,'ltv_v1')
('activo','noi_mensual',None,'raw_er_noi_v1')
('activo','noi_mensual',None,'cdg_noi_split_v1')
('activo','noi_mes',None,'SUM(monto_clp) del mes')
('activo','noi_u12m',None,'SUM NOI 12 meses trailing')
('fondo','ltv',None,'ltv_v1')
('fondo','noi_mes',None,'noi_mes_v1')
('fondo','noi_mes',None,'Torre A + Boulevard NOI del mes')
('fondo','noi_mes',None,'SUM(noi_mensual(activo) x participacion_efectiva(...)')
('fondo','noi_u12m',None,'noi_u12m_mensual_v1')
('fondo','noi_u12m',None,'SUM NOI Fondo PT 12 meses trailing')
('fondo','noi_u12m',None,'SUM NOI Fondo TRI (ponderado) 12 meses trailing')
```

Conclusiones confirmadas:

- `ltv` existe con una **única** fórmula sistemática (`ltv_v1`) en ambos
  granos → catalogable como canónico en fondo y activo.
- `noi_mensual` existe **sólo** en grano `activo`. En grano `fondo` sólo hay
  `noi_mes`/`noi_u12m` con fórmulas *ad hoc* escritas a mano por fondo, sin
  metodología sistemática única → **no se cataloga NOI a nivel fondo**.

## 4. Diseño

### 4.1 Unidades y escala de presentación (D1)

- `MetricDefinition` gana un campo opcional `display_unit`.
- Nuevos códigos de unidad: `ratio_0_1` y `clp`.
- Nuevo valor de `display_unit`: `percent` (único soportado en v1).
- El catálogo valida `display_unit ∈ {None, "percent"}` y que
  `display_unit == "percent"` sólo se combine con `unit == "ratio_0_1"`.

**Regla crítica**: la transformación ratio → porcentaje ocurre en un único
formateador determinista compartido (`tools/analytics/formatting.py`) que
corre **después** del binding de evidencia (5.3/5.4) y **antes** de la
presentación final. La evidencia y los claims conservan siempre el valor
semántico crudo (`0.7115…`, `unit="ratio_0_1"`); los guards comparan claim vs
hecho con ese valor crudo, sin cambios. Sólo el texto renderizado aplica
`display_unit`.

`render_metric_value(metric_key, value, unit)`:

1. Si `metric_key` no está en el catálogo → `f"{value}{unit}"` (compatibilidad
   con fixtures/legado; ningún llamador real cae aquí).
2. Si `unit=="ratio_0_1"` y `display_unit=="percent"` → `f"{value*100:.2f}%"`.
3. Si no → `f"{value}{sufijo(unit)}"` con
   `{"pct_0_100": "%", "m2": " m2", "clp": " CLP", "ratio_0_1": ""}`.

El redondeo a dos decimales se aplica **sólo** cuando hubo conversión de
escala: así `vacancia_pct_fondo` (sin `display_unit`) sigue renderizando
`5.945%` sin cambio alguno (regresión cerrada por test), y LTV rinde
`71.15%` — nunca `0.7115%` ni `7115%`.

Puntos de conexión (todos post-binding):

- `canonical_guard.validate_and_render` — rama `canonical_metric_ref`.
- `coverage_guard.validate_and_render` — rama `canonical_metric_ref`.
- `coverage_guard._render_governed` — listado por entidad.
- `coverage_guard._render_fact_human` — fallback fail-closed.

Efecto colateral deseado: hoy la rama de éxito emite el **código interno** de
unidad (`5.945pct_0_100`). Con el formateador pasa a `5.945%`.

### 4.2 Métricas nuevas del catálogo

| key | grano | unit | display_unit | source_kind | access |
|---|---|---|---|---|---|
| `ltv_fondo` | fund | `ratio_0_1` | `percent` | canonical | `derived_kpi{fondo, ltv}` |
| `ltv_activo` | asset | `ratio_0_1` | `percent` | canonical | `derived_kpi{activo, ltv}` |
| `noi_mensual_activo` | asset | `clp` | — | canonical | `derived_kpi{activo, noi_mensual}` |

`allowed_dimensions` de las métricas de activo incluye `fund`, `asset`,
`period` para habilitar ranking/breakdown por fondo.

**Corrección de `capability_metric_keys`**: hoy `asset_breakdown` exige
`source_kind == "breakdown"`, lo que excluiría a `ltv_activo` y
`noi_mensual_activo` (que son `canonical`). El criterio pasa a ser puramente
dimensional —grano `asset` y `{fund, asset} ⊆ allowed_dimensions`— sin ramas
por métrica. `source_kind` sigue describiendo la autoridad del dato, no la
operación permitida.

Valores de referencia (2026-06): LTV fondo TRI 0.61016…, PT 0.81224…, Apo
0.73479…; LTV activo Apo3001 0.71151… (→ 71.15 %), Boulevard 1.20963…
(outlier de calidad de dato, se mantiene sin recorte).

### 4.3 `_derived_sql` con alcance de activo (aditivo)

La ruta de fondo actual queda **byte-idéntica**. Se agregan dos ramas cuando
`access.entity_type == 'activo'`:

- **lookup por activos explícitos**: filtro `entidad_key IN (assets)` con
  `entidad_tipo='activo'`; `entity_type="asset"`.
- **breakdown/ranking por fondo**: join contra `dim_activo` sobre
  `fondo_key = ?` (mismo patrón que `_view_sql`), con filtro opcional de
  subconjunto `entidad_key IN (assets)`, y `ORDER BY valor ASC|DESC` +
  `LIMIT`.

Todo con SQL parametrizado; nunca interpolación de valores.

### 4.4 Contratos de lookup y breakdown

- **`analytics_lookup_asset`**: métrica de grano activo + **uno o más**
  `assets` canónicos (el campo pasa de string a lista).
- **`analytics_breakdown_asset`**: alcance `fund` + subconjunto opcional
  `assets`.

Validación del subconjunto (para ambos casos donde hay fondo de referencia):
cada activo pedido debe (a) pertenecer al fondo (`dim_activo.fondo_key`) y
(b) ser temporalmente aplicable (`vigente_hasta IS NULL OR vigente_hasta >=
period`), con la misma lógica de `expected_asset_universe`. Si no pertenece →
error explícito tipo `SemanticQueryError`. Si pertenece pero no tiene fila de
KPI → sigue formando parte del universo esperado y la cobertura queda
`partial`, nunca se descarta en silencio.

### 4.5 Cobertura consciente del subconjunto

`_governed_dataset_coverage`: cuando la petición trajo `assets` explícitos en
un breakdown, el universo esperado **es ese subconjunto validado**, no el
`expected_asset_universe(fund)` completo. `status="complete"` sii cada miembro
del subconjunto tiene fila; si no, `partial`. Sin subconjunto explícito, el
comportamiento no cambia.

Esto es lo que permite el caso 07 (rankear 3 activos nombrados) sin exigir
cobertura de los 12 activos de TRI.

### 4.6 `list_assets` — enumeración de entidades

Nueva acción `ListAssetsAction`, que consulta `dim_activo` + `dim_fondo`
directamente (no es una métrica, no pasa por el catálogo). Argumentos:
`fund` (requerido) y `period` (opcional, nullable).

- Con `period` → universo aplicable a ese período (`vigente_hasta IS NULL OR
  vigente_hasta >= period`).
- Sin `period` → universo vigente hoy (`vigente_hasta IS NULL`).

Emite `ToolEvidence(evidence_class="governed_dataset")` con un hecho por
activo (`entity_id=activo_key`, más nombre y `vigente_hasta`), y cobertura
**derivada** de la misma semántica de universo (nunca la cadena literal
`"complete"` hardcodeada). `universe_kind="fund_assets"`.

Además, cada fila reporta si el activo está vigente o es histórico, lo que es
lo que el caso 05 exige (Strip Machalí marcado como divestido).

### 4.7 Escalar multi-fila → `governed_dataset(period_range)` (D2/D3)

Cuando `result_kind=="scalar"` y `len(rows)>1`, la evidencia pasa a ser
`governed_dataset` con `coverage.universe_kind = "period_range"` y
`semantic_contract.universe_kind = "period_range"`. Con ese marcador:

- No se invoca `expected_asset_universe`: una serie temporal no tiene
  "universo de activos", y encuadrarla como parcial/completa sobre activos
  sería semánticamente falso. La cobertura reporta el rango de períodos
  observados con `status="complete"` respecto de ese rango.
- La identidad por fila se preserva como (entidad, período).

**Binding con selección de período** (`coverage_guard`): el índice de hechos
deja de ser `{entity_id: fact}` sobre todos los hechos y pasa a construirse
**tras filtrar por el período del claim**:

```
candidates = [f for f in item.facts if f.get("period") == claim.get("period")]
```

- Si tras el filtro hay entidades duplicadas → `binding_mismatch` (ambigüedad,
  cierre en falso).
- Si el período pedido no existe entre los hechos → el subconjunto de
  `entity_ids` no queda contenido → `binding_mismatch` → cierre en falso.

Para la evidencia de breakdown (todos los hechos comparten período) el filtro
es idempotente: el chequeo posterior de igualdad de período ya lo garantizaba,
por lo que el comportamiento existente no cambia.

Resultado: una evidencia 2020-01..2026-12 nunca puede renderizar el punto de
2020 cuando la pregunta es por 2026-06; o se liga el hecho exacto de 2026-06,
o se cierra en falso.

## 5. No-objetivos

- No se toca la lógica central de comparación de los guards más allá de: el
  enganche del formateador en render, el universo de cobertura por
  subconjunto, y el filtrado por período en el binding gobernado.
- No se agregan nuevas estrategias de acceso más allá de extender
  `_derived_sql`.
- No hay migraciones de esquema. Si alguna resultara inevitable, se detiene el
  trabajo y se reporta como bloqueo arquitectónico.
- No se corrige la provenance incompleta de `_view_sql` (`ingest_run_id` NULL)
  salvo que bloquee un golden.

## 6. Validación

1. Unitarios: catálogo (campos/unidades nuevas), formateador (golden
   0.7115→`71.15%`, y `vacancia_pct_fondo` sin cambio), ejecutor (alcance de
   activo, subconjunto explícito, universo completo, resultado multi-período),
   construcción de evidencia, cobertura de enumeración con y sin período,
   cobertura parcial por subconjunto.
2. Suite completa existente sin regresiones.
3. Reproducción offline determinista de los casos Alpha 02, 03, 05, 06, 07,
   08 y 12 sobre los mismos componentes de la ruta gobernada.
4. Smoke con proveedor real: lookup canónico de LTV, ranking gobernado y
   consulta canónica multi-período.
5. Re-ejecución del eval Alpha completo (15 casos, sin modificar `cases.json`).
