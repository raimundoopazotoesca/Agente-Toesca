# Matriz de claves ambiguas en `derived_kpi` — `Apoquindo` y `Fondo Apoquindo`

**Fecha:** 2026-07-24 · **Estado:** análisis entregado, clasificación pendiente de decisión humana
**Método:** consultas directas a `memory/agente_toesca_v2.db` + rastreo del script generador. Ninguna conclusión se basa en el nombre de la clave; todas las equivalencias están verificadas numéricamente.

> **Corrección a un supuesto previo:** en `ROADMAP.md` v2.0 planteé que `Fondo Apoquindo` podía ser la participación de TRI en el fondo Apo (look-through). **Es falso.** La verificación numérica muestra que es el agregado de los dos activos del fondo. Ninguna de las dos claves representa la participación de TRI.

---

## 1. Matriz `Apoquindo` (178 filas)

| Atributo | Valor verificado |
|---|---|
| **KPIs asociados** | `noi_mensual` (89 filas) · `ingresos_mensual` (89 filas) |
| **Rango de fechas** | 2019-01 → 2026-05 (89 meses continuos) |
| **Filas por KPI y período** | exactamente 1 fila por KPI por mes; sin `variante` |
| **Receta / fórmula** | `raw_er_noi_v1` y `raw_er_ingresos_v1` |
| **Script generador** | `scripts/consolidate_noi_tri.py` y `scripts/consolidate_ingresos_tri.py`. Ambos declaran el mapa de agregación explícito: `"Apoquindo": ["Apo4501", "Apo4700"]` (líneas 37 y 34 respectivamente) |
| **Fecha de cómputo** | 2026-07-20 17:57 (generación reciente, un solo lote) |
| **`entidad_tipo`** | `activo` ← **etiquetado incorrecto**: no es un activo, es un agregado de dos |
| **Unidad** | `UF` (consistente con la convención heredada de ER Apo/PT) |
| **Trazabilidad** | `ingest_run_id` NULL en las 178 filas. Trazabilidad indirecta: `formula` + `computed_at` + el mapa hardcodeado en el script |
| **Valores representativos (`noi_mensual`, UF)** | 2019-01: 16.590,2 · 2021-06: 13.799,8 · 2024-01: 11.513,9 · 2025-12: 13.808,8 · 2026-05: 14.088,1 |

### Comparación contra la suma de 4501 + 4700

Contra `raw_er_activo_line` (suma de líneas con `es_operacional=1`, `superseded_at IS NULL`) para `Apo4501`+`Apo4700`:

| Período | `Apoquindo`.noi_mensual | Suma ER 4501+4700 | Δ | Solo 4501 |
|---|---:|---:|---:|---:|
| 2019-01 | 16.590,2 | 16.590,2 | **0,0** | 13.063,0 |
| 2021-06 | 13.799,8 | 13.799,8 | **0,0** | 10.988,1 |
| 2024-01 | 11.513,9 | 11.513,9 | **0,0** | 8.768,7 |
| 2025-12 | 13.808,8 | 13.808,8 | **0,0** | 11.601,0 |
| 2026-05 | 14.088,1 | 14.088,1 | **0,0** | 11.617,1 |

**Coincidencia exacta en todos los períodos muestreados.** `Apoquindo` = NOI agregado de Apo4501 + Apo4700, calculado desde ER raw.

### Comparación contra KPIs del fondo `Apo`
El fondo `Apo` (`entidad_tipo='fondo'`) **no tiene** `noi_mensual` ni `ingresos_mensual`; solo tiene `noi_u12m` y `ingresos_u12m` (83 filas cada uno, 2019-07→2026-05, recetas `noi_u12m_mensual_v1` / `ingresos_u12m_mensual_v1`). Es decir: **`Apoquindo` es de hecho el NOI mensual del fondo Apo**, guardado un nivel más abajo de donde corresponde. Los U12M del fondo se calculan sobre esta serie.

### Comparación contra la participación de TRI
No corresponde: los valores son el 100% de los dos activos, sin ponderar por el 30% de TRI. La ponderación look-through vive correctamente en `v_activo_fondo_efectivo` (`Apo4501`/`Apo4700` → TRI al 0,3). `Apoquindo` **no** es una vista de TRI.

### Consumidores vigentes ⚠️
- `tools/noi_query.py:24` incluye `("Apoquindo", _RECIPE)` en su catálogo de entidades.
- `tools/db_chat.py:247` documenta `Apoquindo` al Asistente como clave válida de `noi_mensual`, y `:252` para `ingresos_mensual`.

**Consecuencia:** renombrar o eliminar esta clave **rompe el Asistente Virtual Inmobiliario Toesca** y `noi_query`. Cualquier cambio requiere actualizar ambos en el mismo commit, más los golden tests del contrato del Asistente (F2.0).

---

## 2. Matriz `Fondo Apoquindo` (91 filas)

| Atributo | Valor verificado |
|---|---|
| **KPIs asociados** | `m2_vacantes` únicamente (91 filas) |
| **Rango de fechas** | 2019-01 → 2026-07 |
| **Filas por KPI y período** | 1 fila por mes; sin `variante` |
| **Receta / fórmula** | `cdg_vacancia_v1` |
| **Script generador** | `tools/db/backfill.py:551` (`upsert ... "m2_vacantes", m2, "m2", "cdg_vacancia_v1"`). La clave sale de un **mapa de números de fila del CDG**: `backfill.py:370` → `56: "Fondo Apoquindo", 57: "Curicó", 58: "Apoquindo 3001"`. O sea, el nombre es la **etiqueta de una fila de la planilla CDG**, no una entidad modelada |
| **Fecha de cómputo** | 2026-05-25 21:21–21:23 |
| **`entidad_tipo`** | `activo` ← **etiquetado incorrecto** (mismo problema) |
| **Unidad** | `m2` |
| **Trazabilidad** | `ingest_run_id` NULL en las 91 filas. **Fuente = CDG**, que está en decomiso (ROADMAP F1.7) → toda la familia `cdg_vacancia_v1` es legacy por definición |
| **Valores representativos (m²)** | 2019-01: 69,0 · 2021-06: 6.539,9 · 2024-01: 4.308,4 · 2025-12: 1.171,0 · 2026-02: 2.118,0 · 2026-07: 0,0 |

### Comparación contra la suma de 4501 + 4700

| Período | `Fondo Apoquindo` | `Apoquindo 4501` | `Apoquindo 4700` | Suma | Δ | `Apoquindo 3001` |
|---|---:|---:|---:|---:|---:|---:|
| 2019-01 | 69,0 | 47,0 | 22,0 | 69,0 | **0,0** | (sin dato) |
| 2021-06 | 6.539,9 | 5.357,4 | 1.182,5 | 6.539,9 | **0,0** | 0,0 |
| 2024-01 | 4.308,4 | 3.720,0 | 588,4 | 4.308,4 | **0,0** | 2.065,0 |
| 2025-12 | 1.171,0 | 340,0 | 831,0 | 1.171,0 | **0,0** | 1.633,0 |
| 2026-02 | 2.118,0 | 1.287,0 | 831,0 | 2.118,0 | **0,0** | 1.632,6 |

**Coincidencia exacta, y excluye deliberadamente a `Apoquindo 3001`** (que pertenece al fondo TRI, no a Apo). Esto confirma dos cosas: (a) `Fondo Apoquindo` = agregado de los dos activos del fondo Apo; (b) el perímetro del fondo está bien aplicado — 3001 no se suma.

### Comparación contra KPIs del fondo `Apo` y contra TRI
El fondo `Apo` no tiene `m2_vacantes` a nivel `fondo`. Igual que en el caso anterior, **`Fondo Apoquindo` es el dato de fondo guardado con `entidad_tipo='activo'`**. No hay ponderación por la participación de TRI (valores al 100%), así que no representa la posición de TRI.

### Nota sobre 2026-07
La fila de 2026-07 con valor 0,0 existe sin contraparte a nivel activo y es posterior al último rent roll ingerido (2026-05). Probable artefacto del backfill desde el CDG (fila vacía leída como 0). **A validar** — un 0 de vacancia leído como dato real sería engañoso.

---

## 3. Conclusión del análisis (sin decidir)

Ambas claves son **la misma entidad conceptual**: el agregado de Apoquindo 4501 + Apoquindo 4700, es decir el portafolio de activos del fondo Apo. Difieren solo en la generación de receta que las creó:

| | `Fondo Apoquindo` | `Apoquindo` |
|---|---|---|
| Generación | 1ª — CDG (`cdg_vacancia_v1`, may-2026) | 2ª — ER raw (`raw_er_*_v1`, jul-2026) |
| KPIs | `m2_vacantes` | `noi_mensual`, `ingresos_mensual` |
| Fuente | CDG (en decomiso) | `raw_er_activo_line` (canónica) |
| Nomenclatura hermana | `Apoquindo 4501/4700/3001` (nombres largos) | `Apo4501/Apo4700/Apo3001` (claves de `dim_activo`) |

**No hay solapamiento de datos:** se verificó que ningún KPI existe simultáneamente bajo la convención corta y la larga para el mismo activo+período (query de solape devolvió 0 filas). `m2_vacantes` existe **solo** con nombres largos; `noi/ingresos/ltv/ltc/duration` **solo** con claves cortas. Por lo tanto **no hay doble conteo** — el problema es de identidad inconsistente, no de duplicación de cifras. Esto es menos grave de lo que reporté en el diagnóstico inicial y no requiere dedup.

## 4. Propuestas de modelado (para elegir)

### 4.1 Para el agregado (ambas claves)
Como confirmaste que un agregado no debe ser un tercer activo, la opción recomendada es **elevarlo a su nivel real**:

**Opción A (recomendada) — es el fondo:** persistir estos KPIs con `entidad_tipo='fondo'`, `entidad_key='Apo'`. Coherente con que `noi_u12m`/`ingresos_u12m` del fondo ya viven ahí, y con el CHECK existente (`fondo|activo|serie`). No requiere migración de esquema. Requiere actualizar `noi_query.py` y el catálogo de `db_chat.py`.

**Opción B — grupo/complejo explícito:** nueva tabla `dim_grupo_activo(grupo_key, fondo_key, nombre)` + `dim_activo_grupo(grupo_key, activo_key)`, y `entidad_tipo='grupo'` (amplía el CHECK). Correcto si en el futuro hay agrupaciones que **no** coinciden con el fondo completo (p.ej. "Centros Comerciales" dentro de TRI, que ya aparece en la página 2 del factsheet de TRI). Más flexible, más costoso.

Mi lectura: A resuelve hoy; B es la forma correcta si vas a modelar subgrupos dentro de TRI. Son compatibles: A ahora, B cuando aparezca el primer grupo que no sea un fondo.

### 4.2 Para la participación de TRI (no existe hoy, y está bien)
No hace falta crear nada: `v_activo_fondo_efectivo` ya expresa el look-through (Apo4501/4700 → TRI al 0,3; Apo3001 → TRI directo al 0,685) y `dim_fondo.fondo_padre`/`participacion_en_padre` guarda la relación PT→TRI 0,333 y Apo→TRI 0,30. La regla a mantener: **la participación se aplica en la consulta/receta, no se materializa como entidad**. Si se necesitara materializar la serie ponderada, hacerlo como `variante='lookthrough_tri'` sobre la entidad del fondo, nunca como un activo nuevo.

### 4.3 Para las claves de nomenclatura larga (`Apoquindo 4501/4700/3001`)
Según tu criterio (preservar histórico, marcar legacy, no mezclar, recalcular desde raw cuando exista el pipeline): dado que su única receta es `cdg_vacancia_v1` y su fuente es el CDG en decomiso, corresponde **marcarlas legacy y recalcular `m2_vacantes` desde `raw_rent_roll_line`** — lo que a su vez depende del backfill histórico de rent roll (F1.6), hoy con un solo período. Hasta entonces, quedan como el único dato de vacancia disponible y deben mostrarse como legacy, no borrarse.

## 5. Mecanismo propuesto para marcar legacy (no ejecutado)

`derived_kpi` no tiene hoy forma de expresar "obsoleto". Propuesta mínima, alineada con la invalidación ya prevista en F1.1:

```sql
ALTER TABLE derived_kpi ADD COLUMN estado TEXT
  CHECK (estado IN ('vigente','legacy','reemplazado')) DEFAULT 'vigente';
ALTER TABLE derived_kpi ADD COLUMN reemplazado_por TEXT;  -- formula/receta que lo sustituye
ALTER TABLE derived_kpi ADD COLUMN stale_at TEXT;         -- ya previsto en F1.1
```

Luego: `UPDATE derived_kpi SET estado='legacy', reemplazado_por=NULL WHERE formula='cdg_vacancia_v1'` cuando exista el reemplazo, y toda lectura de negocio filtra `estado='vigente'` (o muestra explícitamente el legacy etiquetado). **No se ejecuta nada de esto hasta tener el pipeline canónico versionado y probado.**

## 6. Decisiones que quedan para ti

1. **Agregado:** ¿Opción A (`entidad_tipo='fondo'`, key `Apo`) u Opción B (`dim_grupo_activo`)? Consideración adicional: la página 2 del factsheet de TRI ya contempla un subtotal "Centros Comerciales", que sería el primer caso de grupo ≠ fondo.
2. **Nombre de las series migradas:** si eliges A, ¿las 178 filas de `Apoquindo` se recalculan bajo `fondo/Apo` con la misma receta (`raw_er_noi_v1`), o se marcan legacy y se recalcula con receta nueva versionada?
3. **`2026-07` de `Fondo Apoquindo`** con valor 0,0: ¿dato real o artefacto del CDG a descartar?
4. **Momento:** ¿se hace junto con el pipeline canónico (F1.1) o antes? Recomiendo con F1.1, porque implica recalcular y tocar el catálogo del Asistente en el mismo movimiento.
