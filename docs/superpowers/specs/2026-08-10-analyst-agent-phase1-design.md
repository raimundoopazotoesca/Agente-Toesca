# Analyst Agent — Fase 1 (understanding + semantic layer)

## Contexto

El chat de negocio actual (`tools/db_chat.py`, servido por `POST /api/chat` en
`scripts/ingesta_server.py:326-334`) responde preguntas sobre
`memory/agente_toesca_v2.db` con un flujo de dos pasadas: Pasada 1 genera SQL
directamente desde la pregunta + un bloque de contexto hardcodeado
(`_BUSINESS_CONTEXT`, `tools/db_chat.py:172-231`) + 17 few-shots
(`_FEW_SHOT_EXAMPLES`, `:611-651`); Pasada 2 sintetiza la respuesta en
markdown desde los resultados. Es usado a diario por el equipo interno vía el
chat bubble del factsheet.

Problemas observados (ver brief original): mala interpretación de preguntas
ambiguas, resolución de entidades/métricas poco confiable, sin verificación
de resultados, sin estado de conversación estructurado, sin forma de medir
si una mejora realmente mejora la calidad de las respuestas.

Esta es la **Fase 1** de una evolución incremental hacia un Analyst Agent.
Fuera de alcance en esta fase: gráficos, Excel dinámico, cambio de
proveedor LLM, refactor de `agent.py` (el agente amplio de automatización,
que NO es el objetivo de este trabajo).

## Qué se mantiene sin cambios

- `_validate_sql` / `_run_sql` (`tools/db_chat.py:517-547`): allowlist
  SELECT/WITH, blocklist, conexión `mode=ro`, LIMIT automático. No se toca.
- El fallback multi-proveedor DeepSeek→Groq→Gemini (`_PROVIDER_LIST`,
  `tools/db_chat.py:38-49`). No se toca.
- El endpoint Flask y su autenticación por `X-Ingesta-Token`.
- `derived_kpi` sigue siendo únicamente cache de **resultados** calculados
  (kpi/variante/formula/valor). La capa semántica nueva describe **qué
  significa y cómo se calcula** cada métrica — son cosas distintas y no se
  mezclan.

## Arquitectura nueva

```
semantic/
  metrics/
    vacancia.yaml
    noi.yaml
    dividend_yield.yaml
    tir.yaml
    tasa_arriendo.yaml
  entities.yaml
  relationships.yaml
  synonyms.yaml
  domains.yaml
  schema/
    metric.schema.json
    entity.schema.json

tools/analyst/
  __init__.py
  semantic_loader.py      # carga + valida YAML contra JSON Schema, cachea en memoria del proceso
  entity_resolver.py      # texto -> {fondo_key|activo_key|sociedad_key}, usa synonyms.yaml + entities.yaml
  intent.py                # pregunta + historial -> IntentResult (metric, entities, period, comparison, confidence)
  conversation_state.py    # dict en memoria del proceso Flask, keyed por session_id
  verified_queries/
    *.yaml                 # question, intent_json, sql validado, notas
  result_checks.py         # aplica invariantes declaradas en metrics/*.yaml sobre el resultado ejecutado

tests/
  eval/
    questions.yaml          # 18 preguntas reales (no solapan con los 17 few-shots existentes)
    run_eval.py             # ejecuta cada pregunta contra db_chat.answer(), compara metric/entity/period esperados
  analyst/
    test_semantic_loader.py
    test_entity_resolver.py
    test_intent.py
    test_result_checks.py
```

### Formato `semantic/metrics/*.yaml`

Un archivo por métrica. Ejemplo real (`vacancia.yaml`), basado en
`tools/db/migrations/077_fix_vacancia_case.sql:23-91` y
`wiki/db.md:365-452`:

```yaml
name: vacancia_pct
business_definition: >
  Porcentaje de superficie (m2 GLA) vacante respecto del total arrendable,
  excluyendo estacionamientos. Unidad vacante = arrendatario = "vacante"
  (case-insensitive) en raw_rent_roll_line.
formula: m2_vacantes / m2_gla
unit: pct_0_100
grain: activo-mes   # también existe a nivel fondo consolidado y por tipo (Oficinas/Locales/Bodegas)
aggregation: weighted_by_participacion   # v_vacancia_activo_efectivo pondera por dim_activo.participacion_fondo_activo
time_behavior: month_end_snapshot
source:
  primary_view: v_vacancia_activo
  by_type_view: v_vacancia_activo_tipo
  fund_rollups:
    PT: v_vacancia_pt_consolidado_tipo
    Apo: v_vacancia_apoquindo_consolidado_tipo
  weighted_view: v_vacancia_activo_efectivo
relevant_tables: [raw_rent_roll_line, dim_activo]
allowed_dimensions: [activo, fondo, tipo_activo, periodo]
synonyms: [vacancia, ocupación, ocupacion, occupancy, tasa de ocupación]
invariants:
  - "0 <= value <= 100"
notes: >
  Estacionamiento excluido de los totales. Bug de case-sensitivity en
  arrendatario='vacante' corregido 2026-08-03 (migración 077) — si una
  respuesta usa una vista anterior a esa migración, desconfiar del dato.
```

Métricas de la Fase 1, con estado de certeza de la definición (todas ya
confirmadas por wiki/migraciones, ninguna se inventa):

| Métrica | Fuente confirmada |
|---|---|
| `vacancia_pct` | `077_fix_vacancia_case.sql`, `wiki/db.md` |
| `noi_u12m` / `noi_mes` | `wiki/kpis_noi_cap_rate_apo.md:10-49` — **nota crítica**: para Apo, `raw_er_activo_line.monto_clp` está en UF, no CLP (`:23-27`); el YAML debe declarar esta trampa de unidad explícitamente para que `result_checks.py` no la deje pasar |
| `dy` / `dy_amort` | `wiki/kpis_rentabilidad_fondos.md:103-153` |
| `tir_contable_desde_inicio` / `tir_bursatil_desde_inicio` | `wiki/tir_contable_desde_inicio.md` |
| `tasa_arriendo_ajustada_{contable,bursatil}` | `wiki/kpis_noi_cap_rate_apo.md` §4/§8/§9 |

Cualquier métrica mencionada en una pregunta futura que no tenga YAML
correspondiente se marca `definicion_pendiente: true` y el agente debe
decirlo explícitamente en vez de inventar una fórmula.

### `entities.yaml` / `relationships.yaml` / `synonyms.yaml`

Se migran los alias hardcodeados hoy en `_BUSINESS_CONTEXT`
(`tools/db_chat.py:188-231`, ej. `"APO"→Apo`, `"Viña"/"Vina"→Viña Centro`,
`"Curicó"/"Power Center"→Mall Curicó`) a `synonyms.yaml`, sin perder ninguna
entrada. `entities.yaml` documenta cada fondo/activo/sociedad con su
`*_key` canónico (fuente: `dim_fondo`, `dim_activo`, `dim_sociedad`).
`relationships.yaml` documenta la jerarquía fondo↔activo↔sociedad,
incluyendo casos ya conocidos como problemáticos en `CLAUDE.md`
(las 4 entidades "Apoquindo": `Apo` fondo, `Apo4501`/`Apo4700` activos de
Apo, `Apo3001` activo de **TRI** no de Apo). `db_chat.py` sigue teniendo su
propio bloque hasta que se complete la migración métrica por métrica —
conviven, no se borra de golpe.

### `intent.py`

Reemplaza la generación directa de SQL en Pasada 1 por un paso intermedio:
una llamada LLM con schema JSON fijo que devuelve
`{metric, entities: [...], period, comparison, confidence}`. Usa
`entity_resolver.py` para normalizar entidades contra `entities.yaml` +
`synonyms.yaml` antes de tocar SQL. Si `confidence` es baja y hay más de una
interpretación plausible, el agente pregunta (no siempre — criterio: baja
confianza + alto impacto de elegir mal, no ambigüedad léxica trivial).

### `conversation_state.py`

Dict en memoria del proceso Flask, keyed por `session_id` (el cliente ya
manda `history`; se añade `session_id` opcional). Guarda
`{last_metric, last_entities, last_period, last_analysis_type}`. Se pierde
en reinicio del server — aceptable, confirmado con el usuario (uso diario
en horario laboral, no crítico persistir entre reinicios).
Usado para resolver "¿y el año pasado?" / "hazlo para Viña Centro" sin
mandar el historial completo al LLM en cada intent call.

### `verified_queries/`

Cada archivo: `question`, `intent` esperado, `sql` validado, notas de por
qué esa forma de la query es la correcta (joins, filtros de
`superseded_at`, etc.). Antes de generar SQL desde cero, se busca por
similitud léxica simple (no embeddings en esta fase) una verified query
parecida y se usa como few-shot dirigido, además de los 17 existentes.

### `result_checks.py`

Aplica `invariants` de `metrics/*.yaml` (ej. `0<=value<=100`) sobre el
resultado antes de la Pasada 2 de síntesis. Si falla, no se responde
directamente — se re-intenta la query una vez con un mensaje de error
explícito al LLM, o si vuelve a fallar, la respuesta final dice
explícitamente que el dato no pudo validarse (nunca se inventa un ajuste).

## Flujo actualizado de `db_chat.answer()`

```
1. intent.py: pregunta + conversation_state -> IntentResult
2. entity_resolver.py: normaliza entities contra entities.yaml/synonyms.yaml
3. si confidence baja y ambigüedad de alto impacto -> pedir aclaración (no siempre)
4. buscar verified_queries/ similar; si hay match fuerte, usar su SQL como base
5. generar/ajustar SQL (Pasada 1 actual, con más contexto dirigido)
6. _validate_sql + _run_sql (sin cambios)
7. result_checks.py sobre el resultado
8. Pasada 2: síntesis de respuesta (sin cambios en el mecanismo, prompt ajustado)
9. actualizar conversation_state
```

## Eval set (`tests/eval/questions.yaml`)

18 preguntas reales, sin solapar con los 17 few-shots existentes en
`db_chat.py`, cubriendo las 5 métricas de la Fase 1 y casos de
ambigüedad/temporalidad/seguimiento conversacional:

```yaml
- question: "¿cómo ha evolucionado la vacancia de Parque Titanium este año?"
  expected_intent: vacancia_trend
  expected_entities: {activo: Parque Titanium}
  expected_period: "2026 YTD"
- question: "vacancia de bodegas en Apoquindo"
  expected_intent: vacancia_snapshot
  expected_entities: {fondo: Apo, tipo_activo: Bodegas}
- question: "¿y el mes anterior?"   # requiere conversation_state previo
  expected_intent: follow_up_same_metric_different_period
- question: "NOI de Viña Centro en los últimos 12 meses"
  expected_intent: noi_u12m
  expected_entities: {activo: Viña Centro}
- question: "compara el NOI de Apo y PT este año"
  expected_intent: noi_comparison
  expected_entities: {fondo: [Apo, PT]}
- question: "dividend yield con amortización de la serie A de TRI"
  expected_intent: dy_amort
  expected_entities: {fondo: TRI, serie: A}
- question: "¿cuál es la TIR desde inicio bursátil de la serie C?"
  expected_intent: tir_bursatil_desde_inicio
  expected_entities: {fondo: TRI, serie: C}
- question: "tasa de arriendo ajustada contable de Apo3001"
  expected_intent: tasa_arriendo
  expected_entities: {activo: Apo3001}
  notes: "Apo3001 pertenece a TRI, no a Apo — valida entity_resolver/relationships.yaml"
- question: "¿cómo viene Parque Titanium?"
  expected_intent: ambiguous_general_status
  notes: "debe preguntar o cubrir ocupación+financiero, no elegir una sola métrica sin avisar"
- question: "vacancia del fondo TRI por tipo de activo"
  expected_intent: vacancia_by_type
  expected_entities: {fondo: TRI}
- question: "NOI de enero 2024 de PT"
  expected_intent: noi_mes
  expected_entities: {fondo: PT}
  expected_period: "2024-01"
- question: "muéstrame lo mismo para Viña Centro"   # sigue a la de PT
  expected_intent: follow_up_same_metric_different_entity
- question: "¿la vacancia de Curicó está sobre 100%?"
  notes: "debe fallar result_checks si el dato viene mal, no reportar >100% sin flag"
- question: "dividend yield de las tres series de TRI, sin amortización"
  expected_intent: dy_comparison
  expected_entities: {fondo: TRI, serie: [A, C, I]}
- question: "¿qué fondo tiene menor vacancia hoy?"
  expected_intent: vacancia_ranking
- question: "TIR contable desde inicio de Apo"
  expected_intent: tir_contable_desde_inicio
  expected_entities: {fondo: Apo}
  notes: "Apo usa método agregado (single aporte), no divisor por cuota — valida metrics/tir.yaml"
- question: "renta promedio UF/m2 en oficinas de Parque Titanium"
  expected_intent: tasa_arriendo
  notes: "no hay vista UF/m2 confirmada — el agente debe decir que la definición está pendiente de validar, no inventar una fórmula"
- question: "capex de Viña Centro este año"
  expected_intent: undefined_metric
  notes: "capex no tiene YAML ni fuente confirmada en esta fase — debe decir explícitamente que no puede responder, no inventar"
```

`run_eval.py` compara `metric`/`entities`/`period` extraídos por
`intent.py` contra lo esperado (no compara el texto final de la respuesta,
que es más difícil de evaluar automáticamente en esta fase). Reporta
accuracy por dimensión (intent/entity/period) para poder medir progreso.

## Testing

- `test_semantic_loader.py`: YAML inválido contra el JSON Schema falla con
  error claro; carga exitosa expone el catálogo esperado.
- `test_entity_resolver.py`: todos los alias migrados desde
  `_BUSINESS_CONTEXT` siguen resolviendo igual; casos de la tabla de las 4
  entidades Apoquindo resuelven a la clave correcta.
- `test_intent.py`: casos representativos del eval set (mock del LLM con
  respuesta JSON fija, no llamada real).
- `test_result_checks.py`: invariant `0<=value<=100` rechaza 134%, acepta 45%.
- `tests/eval/run_eval.py`: no es parte de la suite de CI normal (llama al
  LLM real) — se corre manualmente como parte de la Fase de verificación,
  igual que hoy se corre `derived_kpi_golden.json`.

## Riesgos / decisiones abiertas dejadas explícitas

- El `intent.py` añade una llamada LLM extra por pregunta (antes había 2
  pasadas, ahora 3). Se acepta el costo/latencia adicional a cambio de
  mejor resolución — a revisar en la fase de evaluación si el impacto en
  UX es aceptable.
- La búsqueda por similitud léxica en `verified_queries/` es una heurística
  simple (no embeddings) para esta fase; si no es suficientemente precisa,
  se reevalúa en una fase posterior — no se agrega infraestructura de
  embeddings ahora sin evidencia de que se necesita.
- Métricas fuera de las 5 listadas (LTV, RCSD, crédito, precio cuota, etc.,
  ya usadas en los 17 few-shots existentes) NO se migran a YAML en esta
  fase — siguen funcionando vía `_BUSINESS_CONTEXT` como hoy. Se migran
  incrementalmente en fases siguientes.
