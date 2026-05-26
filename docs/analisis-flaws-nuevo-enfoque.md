# Análisis de flaws — Nuevo enfoque DB-first

**Fecha:** 2026-05-26  
**Contexto:** Análisis del enfoque "agente → DB → reemplaza CDG" post-migración Fase 2.

## Flaws identificados (15)

### 🔴 Críticos (bloqueadores)

| # | Flaw | Estado |
|---|------|--------|
| 1 | `dim_cuenta.tipo_eeff` / `signo` vacíos — resuelto con `seccion`+`es_operacional` en `raw_er_activo_line` | ✅ Resuelto 2026-05-26 |
| 2 | Sin catálogo de `dim_recipe` — cualquier `compute_*` inventa recipes ad-hoc | ❌ Abierto |
| 3 | Invalidación de `derived_kpi` no implementada — re-ingest no invalida derived | ❌ Abierto |

### 🟠 Serios (riesgo silencioso)

| # | Flaw | Estado |
|---|------|--------|
| 4 | Best-effort dual-write sin job de reconciliación — DB puede desfasarse del Excel sin alerting | ❌ Abierto |
| 5 | `file_hash` idempotente pero patrón `mark_superseded` no documentado ni testeado | ❌ Abierto |
| 6 | Definición de "mes cerrado" no explícita — cada `compute_*` decide distinto | ❌ Abierto |
| 7 | Sin framework de reconciliación legacy↔nuevo (`cdg_noi_real_v1` vs `eerr_calculado_v1`) | ❌ Abierto |

### 🟡 Arquitecturales

| # | Flaw | Estado |
|---|------|--------|
| 8 | Sub-segmentaciones (PT Torre A/Boulevard, Apo 4501/4700) hardcodeadas en Python | ❌ Abierto |
| 9 | Migraciones se aplican automáticamente al importar `memory_tools` — riesgo en prod | ❌ Abierto |
| 10 | Dashboard: dos stacks coexisten (HTML autocontenido vs Streamlit) — divergirán | ❌ Abierto |
| 11 | Skills custom viven en `~/.claude/skills/`, no en el repo — pérdida en cambio de máquina | ❌ Abierto |

### 🟢 Deuda técnica / proceso

| # | Flaw | Estado |
|---|------|--------|
| 12 | Tests cubren repos CRUD, no invariantes de negocio (suma fondo=activos, no futuros, no Machalí) | ❌ Abierto |
| 13 | Decisiones duplicadas en memory/*.md + wiki/db.md + HANDOFF — divergirán | ❌ Abierto |
| 14 | Performance: CDG 14MB/12s sigue siendo cuello de botella en dev/tests | ❌ Abierto |
| 15 | Sin criterio de corte del CDG — "reemplazar el CDG" es aspiración, no proyecto con métrica de salida | ❌ Abierto |

---

## Detalle técnico por flaw

### ✅ Flaw 1 — `dim_cuenta` sin clasificar (RESUELTO 2026-05-26)

**Solución adoptada:** en vez de poblar `dim_cuenta` con un plan de cuentas externo, se modificó el parser `_leer_eeff_estado_resultado` para trackear la sección activa del EERR (los headers de sección ya existen en el archivo). Ahora `raw_er_activo_line` tiene dos columnas nuevas:
- `seccion TEXT` — etiqueta de sección tal como aparece en el EERR  
- `es_operacional INTEGER` — 1 si precede a "TOTAL OPERACIONAL", 0 si no

**NOI calculable directamente:**
```sql
SELECT SUM(monto_clp) FROM raw_er_activo_line
WHERE activo_key=? AND periodo=? AND es_operacional=1 AND superseded_at IS NULL
```

**Validación Curicó 2026-01:** raw=62.5M CLP ≈ CDG=64.4M CLP (UF×precio). Match correcto.  
**Viña:** brecha vs CDG pendiente de reconciliación (ver Flaw 7 — diferencia metodológica probable en depreciaciación/incobrables).

**Nota sobre `seccion=None`:** los primeros accounts de Viña (4-1-01-*) aparecen antes del primer header de sección en el archivo. Tienen `es_operacional=1` correcto, solo les falta la etiqueta de sección. No afecta el cálculo de NOI.

**Archivos modificados:** `tools/db/migrations/009_add_seccion_er.sql`, `tools/db/repo_er_activo.py`, `tools/noi_tools.py`, `tools/db/backfill.py`.

---

### Flaw 2 — Sin `dim_recipe`

**Síntoma:** `derived_kpi.recipe` es un string libre. Cualquier función puede crear `recipe='foo_v3'` sin registro.  
**Riesgo:** No hay trazabilidad de qué calcula cada recipe, qué inputs usa, cuándo se depreca.  
**Fix:** Tabla `dim_recipe(recipe_id, descripcion, inputs, status, created_at)` con FK desde `derived_kpi`.

---

### Flaw 3 — Invalidación no implementada

**Síntoma:** Propuesto en memoria `noi-desde-eerr-y-caching-inteligente` pero sin código.  
**Riesgo:** Re-ingest de raw no marca como stale los derived que dependen de él → KPIs viejos servidos.  
**Fix:** Columna `stale_at` en `derived_kpi` + trigger o función `invalidar_derived(ingest_run_id)` que la setea.  
**Tamaño:** ~1 migración + 30-50 líneas.

---

### Flaw 4 — Dual-write sin reconciliación

**Síntoma:** `_persist_*` captura excepciones y continúa. No hay job posterior que verifique paridad.  
**Riesgo:** CDG dice X, DB dice Y, nadie lo sabe hasta que alguien pregunta manualmente.  
**Fix:** Script semanal `python -m tools.db.verificar_paridad` que compare conteos NOI/vacancia por mes y emita alerta si delta > umbral.

---

### Flaw 5 — Patrón `mark_superseded` incompleto

**Síntoma:** Si proveedor reenvía RR corregido (distinto hash), hay dos versiones de raw para el mismo período. `compute_*` suma ambas.  
**Riesgo:** Doble conteo silencioso en vacancia/NOI.  
**Fix:** Documentar ciclo de vida: `ingest_run` nuevo para mismo (proveedor, periodo) → marcar superseded el run anterior → `compute_*` filtra solo runs no-superseded. Agregar test.

---

### Flaw 6 — "Mes cerrado" sin definición

**Síntoma:** La caching policy dice "persistir si mes cerrado", pero no hay función `es_periodo_cerrado(activo, periodo)`.  
**Riesgo:** Cada `compute_*` define su propia heurística (algunos usan `date.today()`, el fix de `backfill_noi` usa la última fila de PT — inconsistente).  
**Fix:** Función única en `tools/db/utils.py` que determine cierre leyendo el `loaded_at` del último ingest_run de un activo+período.

---

### Flaw 7 — Sin reconciliación legacy↔nuevo

**Síntoma:** `cdg_noi_real_v1` ya existe en DB. Cuando `eerr_calculado_v1` esté listo, habrá diferencias.  
**Riesgo:** No sabremos si las diferencias son bugs o diferencias metodológicas legítimas.  
**Fix:** Tool `consultar_diff_recipes(kpi, activo, periodo_inicio, periodo_fin)` + panel en dashboard "Legacy vs Nuevo".

---

### Flaw 8 — Sub-segmentaciones hardcodeadas

**Síntoma:** PT (Torre A/Boulevard/Bodegas) y Apoquindo (4501/4700) como reglas en `rentroll_tools._read_source_data`.  
**Riesgo:** Nuevo activo con split → hay que tocar código.  
**Fix:** Tabla `dim_segmento(activo_key, regla_columna, regla_valor, segmento)` — mapeo declarativo.

---

### Flaw 9 — Migraciones auto en import

**Síntoma:** `apply_migrations` corre al importar `memory_tools`.  
**Riesgo:** Crash a mitad de migración deja DB inconsistente en runtime del agente.  
**Fix:** Cada migración en su propia transacción `BEGIN IMMEDIATE`. Flag `AGENT_AUTOMIGRATE=0` para deshabilitar en prod.

---

### Flaw 10 — Dos stacks de dashboard

**Síntoma:** `tools/db/dashboard.py` genera HTML estático. Skill `db-dashboard-expert` propone Streamlit.  
**Riesgo:** Divergirán. Funcionalidades nuevas se implementan solo en uno.  
**Fix:** Decidir uno. Recomendación: Streamlit (más mantenible, interactivo). Deprecar HTML o usarlo solo para snapshot de CI.

---

### Flaw 11 — Skills fuera del repo

**Síntoma:** `db-ingestion-expert` y `db-dashboard-expert` en `~/.claude/skills/`.  
**Riesgo:** Pérdida en cambio de máquina o reinstalación.  
**Fix:** Copiar a `automation_agent/.claude/skills/` y commitear. Agregar `scripts/install_skills.ps1` que haga symlink.

---

### Flaw 12 — Sin tests de invariantes de negocio

**Síntoma:** 91 tests cubren repos, no lógica de negocio E2E.  
**Fix:** Agregar en `tests/db/test_invariantes.py`:
- `sum(noi_activos_fondo) ≈ noi_fondo` (tolerancia 1%)
- `vacancia_pct ∈ [0, 1]`
- No existe `fondo_key LIKE 'A&R%'`
- No existe `activo_key = 'machali'`
- No hay `derived_kpi.periodo > ultimo_ingest_cerrado`

---

### Flaw 13 — Documentación triplicada

**Síntoma:** memory/*.md + wiki/db.md + docs/HANDOFF divergen.  
**Fix:** `wiki/db.md` = fuente única. Memories solo llevan punteros. HANDOFFs son temporales y se archivan.

---

### Flaw 14 — CDG lento en dev/tests

**Síntoma:** Backfill y cross-check leen el CDG entero (14MB, ~12s).  
**Fix:** Serializar hojas clave del CDG a parquet en `memory/snapshots/` y leer desde ahí en tests y dev. Regenerar snapshot cuando llegue nuevo CDG.

---

### Flaw 15 — Sin criterio de corte del CDG

**Síntoma:** "Reemplazar el CDG" es la visión, pero sin métrica de salida ni timeline.  
**Fix:** Definir: "El CDG es reemplazable cuando `eerr_calculado_v1` discrepa <1% de `cdg_noi_real_v1` durante 3 meses consecutivos". Agregar a `wiki/db.md#roadmap`.

---

## Orden de ataque sugerido

1. **Flaw 3** — Invalidación `stale_at` (pequeño, alto impacto)
2. **Flaw 1** — Poblar `dim_cuenta` (bloqueador de toda la Fase 3)
3. **Flaw 12** — Tests de invariantes (bajo costo, cubre regresiones)
4. **Flaw 6** — `es_periodo_cerrado` única (unifica lógica dispersa)
5. **Flaw 4** — Script de reconciliación semanal
6. **Flaw 5** — Documentar + testear `mark_superseded`
7. **Flaw 7** — Tool de diff legacy↔nuevo
8. **Flaws 8-15** — Siguiente ciclo

---

*Generado 2026-05-26. Actualizar estado (❌/✅) a medida que se resuelvan.*
