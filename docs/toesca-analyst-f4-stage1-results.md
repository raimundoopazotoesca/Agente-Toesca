# F4 Stage 1 — resultados y aprendizajes

**Estado: PASS / KEEP.** Congelado 2026-08-19. Decisiones de esta etapa (mantener
4 investigación + 1 síntesis reservada, no revertir, no correr Terra/Sol de
nuevo, no tocar Holdout) quedan fijadas por decisión explícita del usuario, no
por este documento — este documento es diagnóstico posterior, no reabre Stage 1.

## Hipótesis

> Reservar la última de 5 rondas de modelo para síntesis (sin herramientas)
> evita perder turns que ya investigaron pero agotaron su presupuesto sin
> producir una respuesta final.

## Cambio implementado

`MAX_TOTAL_MODEL_ROUNDS = 5` sin cambios respecto a Round B. Estructura interna:
**4 rondas de investigación + 1 ronda reservada de síntesis** (sin tools,
`tool_choice="none"`, verificado empíricamente contra las tres SDKs). El
presupuesto total de cómputo por turn no aumentó.

## Baseline — B27 (Track B, Terra, pre-F4)

```
51/51 cases, 79/79 turns
completeness            0.5772
factual_correctness     0.6431  (n=51)
conversational_quality  0.5934
tool_correctness        0.4667  (n=9)
model rounds: 282  |  SQL: 393  |  tool calls: 408
latency mean 15.2s | median 13.9s | p90 29.5s
29/79 turns reached round 5
17/79 turns terminaron con placeholder ("no se alcanzó una respuesta final")
```

## Resultados — F4 Stage 1 (run_id `round-b-f4s1-terra`, code_commit `2ab06e5`)

```
51/51 cases, 79/79 turns, 0 retries, 0 provider failures
completeness            0.6344  (+0.0572)
factual_correctness     0.5439  (n=66, -0.0992 vs oficial B27 -- ver diagnóstico matched abajo)
conversational_quality  0.6543  (+0.0610)
tool_correctness         0.4333  (n=9, -0.0333)
model rounds: 265 (-17)  |  SQL: 305 (-88)  |  tool calls: 321 (-87)
latency mean 16.1s | median 11.8s | p90 30.7s
32/79 turns reached round 5
0/79 turns terminaron con placeholder
```

**17 → 0.** Confirmado sin excepciones.

## Diagnóstico: matched factual correctness

El agregado oficial (`0.6431 n=51` vs `0.5439 n=66`) no es comparable directamente
porque el denominador cambió: F4 rescató 15 turns que antes ni siquiera se
puntuaban en `factual_correctness` (por el carve-out `if not has_numbers(...)`
de `gates.py`, que marca `unscored` cualquier respuesta sin reclamo numérico).

Partición exacta sobre los 79 turns, verificada por suma:

| Grupo | n | mean B27 | mean F4 | delta |
|---|---:|---:|---:|---:|
| **Matched** (puntuados en ambos) | 51 | 0.6431 | 0.6294 | −0.0137 |
| **Newly scored** (solo F4) | 15 | — | 0.2533 | — |
| **Lost scored** (solo B27) | 0 | — | — | — |

`51 + 15 = 66` (n oficial F4). `51 + 0 = 51` (n oficial B27).

**Conclusión:** en el conjunto comparable manzana-con-manzana, `factual_correctness`
cae solo **1.4 puntos** (0.6431→0.6294), no 9.9. El resto de la caída agregada
(−8.6pp) es enteramente mecánico: 15 turns que antes no afirmaban nada numérico
ahora sí lo hacen (correctamente en 3/15, parcialmente en 2/15, incorrectamente
en 10/15) — preguntas L4-L6 de atribución causal genuinamente difíciles en 4
rondas. Script: `eval/analysis/f4_stage1_matched_factual.py`.

De los 4 turns que sí bajan en el conjunto matched (`tae-l5-003`,
`tce-decisioncommittee-001` turn2, `tce-investigationdrilldown-001`,
`tce-investigationhypothesis-001`), 2 son las regresiones atribuibles al
presupuesto (ver abajo) y 2 muestran mismas rondas/SQL en ambas corridas — ruido
del modelo, no efecto de F4.

## El trade-off: 2 regresiones atribuibles al presupuesto 4+1

De los 12 turns que en B27 llegaban a ronda 5 con respuesta real (no placeholder),
5 regresan en total; de esos, **2 tienen menos rondas efectivas de investigación
en F4 con el mismo total de llamadas al modelo** (evidencia directa: mismo
`model_rounds=5`, menos `executed_sql`):

| Turn | B27 SQL | F4 SQL | B27 dims | F4 dims |
|---|---:|---:|---|---|
| `tae-l5-003` | 16 | 13 | 0.6/0.6/0.5/0.5 | 0.3/0.3/0.0/0.3 |
| `tce-investigationdrilldown-001` | 13 | 9 | 1.0/1.0/1.0 | 0.4/0.4/0.4 |

**`tae-l5-003`** ("¿qué te preocupa de Apo en 2026?"): ambas respuestas identifican
correctamente refinanciamiento + vacancia como riesgos, con cifras de deuda/LTV/DSCR
idénticas. La diferencia está en el detalle de vacancia por activo (Apo4501 vs
Apo4700): el `primary_fact` exige la cifra de junio de Apo4501; B27 la acierta,
F4 no (dispara gate C1, ceiling 0.30, `factual_correctness` a cero). Verificado con
el checker real: B27 satisface el hecho de junio y falla el de enero; F4 al revés.
F4 sí consultó equivalentemente los datos de vacancia por activo (queries de
distinto fraseo pero mismo alcance temporal), pero la síntesis final reportó la
vacancia consolidada de Apo por *tipo de unidad* en vez de desglosar Apo4501 vs
Apo4700 en junio con la precisión que el `primary_fact` exige. **No es
claramente "menos evidencia disponible" — es una elección de presentación/nivel
de agregación en la síntesis** que coincide con tener una ronda de investigación
menos.

**`tce-investigationdrilldown-001`** ("¿qué fondo merece más atención?"): **ambas
respuestas eligen "Apo" como prioridad — ninguna sigue el `expected_behavior` del
caso (que espera "PT" por LTV más alto)**, y ambas citan el mismo LTV de PT
(81,2%) correctamente. La caída de 1.0→0.4 en F4 es un **artefacto del gate C3
(período)**: B27 escribe "junio de 2026" en prosa; F4 solo usa el formato de
encabezado de tabla `"(jun-2026)"`, que el regex determinístico `periods_mentioned`
no reconoce (verificado ejecutando el grader real: `periods_mentioned` extrae
`{'2026-06','2027-01','2029-11'}` del texto de B27 y solo `{'2025-06'}` del de F4,
pese a que "(jun-2026)" aparece 5+ veces en las tablas). El gate C3 aplica un techo
de 0.40 a las tres dimensiones simultáneamente. **Esta regresión específica no es
producto del presupuesto reducido — es sensibilidad del grader determinístico al
formato de fecha en tablas**, y habría ocurrido igual con 5 rondas de investigación.

### Principios generales sobre "material late query"

De los dos casos y de la comparación de conjuntos de SQL ejecutados (ningún query
es literalmente compartido entre corridas — hay no-determinismo real de fraseo
SQL entre llamadas API separadas, así que no existe una atribución byte-exacta
"esto hizo específicamente R5"):

1. **La ronda tardía que realmente importó en B27 no descubrió un dato nuevo
   categóricamente ausente** — ambos casos muestran que F4 tenía acceso
   equivalente a la misma tabla/vista con consultas de alcance similar. Lo que
   se perdió fue **una consulta adicional de verificación/desglose** que habría
   confirmado o afinado un número ya parcialmente obtenido, no una fuente de
   evidencia nueva.
2. Encaja mejor en la categoría **"amplía precisión/desglose"** que en
   "descubre dato nuevo": ambos casos rescatables muestran evidencia de nivel
   agregado ya presente antes de R5; lo que R5 aportaba en B27 era el
   desglose fino (por activo, por tipo) que el `primary_fact`/gate exige
   exactamente.
3. **No toda caída de score al reducir rondas es evidencia perdida.** Uno de
   los dos casos regresados (`tce-investigationdrilldown-001`) es enteramente
   un artefacto del grader (formato de fecha), no una pérdida real de
   capacidad de investigación. Cualquier futura decisión de presupuesto debe
   separar ambas señales antes de actuar.

## Clasificación de los 17 rescatados

Estado de la evidencia justo antes de la síntesis F4, leído directamente de
`executed_sql` + `final_answer` + specs de caso + valores resueltos:

| Turn | Categoría | Rondas | SQL | Problema (resumen) | Calidad respuesta | Gap principal |
|---|---|---:|---:|---|---|---|
| `tae-l1-002` | **D** (recon.) | 5 | 4 | Recalculó vacancia TRI "efectiva" (look-through) en vez de usar `derived_kpi.vacancia_pct=5.945%` (canónico) | Coherente, mal número (4.90%) | Metodología equivocada, no falta de datos |
| `tae-l2-003` | **B**, sec. C | 5 | 5 | Solo verificó que existían registros de LTV; nunca extrajo los valores numéricos | Honesta ("sería especulativo afirmarlo") | Gastó rondas en metadata, no en el valor |
| `tae-l4-002` | **D**, sec. E | 5 | 10 | Atribución causal multi-activo con ponderación por participación (tercios, 80%) | Estructurada, número no verificado | Cálculo look-through complejo sin checkpoint |
| `tae-l4-003` | **A** | 5 | 11 | — | 0.7/1.0/1.0 — éxito | ninguno relevante |
| `tae-l4-004` | **E**, sec. B | 5 | 7 | Explica caída LTV oct., declara incertidumbre honesta sobre repunte dic. | Buena, prudente | *Nota: score 0.4 uniforme es en parte artefacto — texto omite el año junto a "octubre"/"diciembre" (ya establecido por la pregunta), el regex de período no los reconoce* |
| `tae-l4-005` | **D** | 5 | 4 | EEFF con líneas duplicadas/ambiguas ("Pasivos corrientes" repetido); no reconcilió pasivo total | Honesta, explica el obstáculo | Reconciliación de plan de cuentas no resuelta |
| `tae-l4-007` | **B**, sec. C | 5 | 14 | Investigación más extensa de los 17 (14 queries: crédito, EEFF, rent roll, tasación); aun así no fijó el hecho requerido | Razonamiento causal coherente | Amplitud sin precisión en el dato exacto |
| `tae-l5-001` | **C**, sec. D | 5 | 4 | NOI concentrado en 4 activos (Viña, Curicó, INMOSA, Sucden); posible alcance incompleto vs el fondo completo | Tabla clara, conclusión razonable | Alcance de activos posiblemente estrecho |
| `tae-l5-005` | **D** | 5 | 6 | Concluye "sin deterioro" mirando solo saldo de deuda absoluto, no LTV | Bien estructurada | Métrica equivocada para la pregunta (leverage ≠ saldo de deuda) |
| `tae-l6-001` | **A** | 5 | 9 | — | 1.0/1.0/1.0 — éxito | ninguno relevante |
| `tae-l6-002` | **B** | 5 | 8 | Briefing multi-tema (leverage+NOI+patrimonio); sustituye dic-2025 por mar-2026 explícitamente por falta de dato | Transparente sobre el gap | No cubrió los 3 required_facts en las rondas disponibles |
| `tae-l8-003` | **A** | 5 | 5 | Declina cuantificar CapEx por ambigüedad real del plan de cuentas | Correcta — decline responsable | ninguno; éxito |
| `tce-ambiguity-003` | **A** | 5 | 6 | — | 0.85 — éxito | ninguno relevante |
| `tce-decisionchallenge-001` | **A** | 5 | 11 | — | 1.0/1.0/1.0 — éxito | ninguno relevante |
| `tce-followup-001` | **D** | 5 | 4 | Mismo patrón que `tae-l1-002`: recalcula vacancia TRI (5.43%, excluye Strip Machalí) en vez de usar `derived_kpi` canónico (5.945%) | Transparente sobre el activo faltante | Mismo root cause repetido: no consulta el KPI precomputado |
| `tce-investigationanomaly-001` t2 | **E** | 1 | 0 | Declina atribuir causalidad; **0 queries en este turn** (posible reuso de contexto de turns previos de la misma conversación) | Razonamiento cauteloso | *Incertidumbre marcada: no está claro si reusar contexto sin re-verificar fue apropiado aquí* |
| `tce-investigationmultidomain-001` | **D** | 5 | 10 | Reporta deuda TRI a **marzo** 2026 (última EEFF trimestral cerrada) cuando se esperaba **junio**; fuentes trimestral vs mensual desalineadas | Cifras coherentes, período equivocado | Reconciliación de granularidad EEFF-trimestral vs KPI-mensual |

**Distribución:**

| Categoría | n (primaria) |
|---|---:|
| A — SUFFICIENT_EVIDENCE (éxito) | 5 |
| B — INSUFFICIENT_EVIDENCE | 3 |
| C — WRONG_OR_MISDIRECTED_EVIDENCE | 1 |
| D — RECONCILIATION_PROBLEM | 6 |
| E — UNSUPPORTED_CAUSALITY | 2 |

**Hallazgo transversal más fuerte:** de los 17, **6 caen en reconciliación** (D),
y dos de ellos (`tae-l1-002`, `tce-followup-001`) comparten exactamente el mismo
root cause verificado: el modelo recalcula un KPI manualmente desde tablas raw
con una metodología propia en vez de consultar el valor ya calculado en
`derived_kpi`. Esto no es un problema del presupuesto de rondas — ocurriría con
cualquier número de rondas si el modelo no aprende a preferir la fuente canónica.

## Stopping diagnostic general

Con la evidencia disponible (79 turns × 2 corridas), respondiendo con la
incertidumbre que corresponde:

- **¿Turns que siguieron investigando con evidencia ya suficiente?** No hay
  señal directa de esto en los datos — B27 no registra en qué ronda la evidencia
  se volvió "suficiente" vs cuándo se detuvo. **No se puede responder sin
  fabricar precisión.**
- **¿Turns que llegaron a síntesis con evidencia insuficiente?** Al menos **3
  de 17** rescatados caen limpiamente en `B — INSUFFICIENT_EVIDENCE`
  (`tae-l2-003`, `tae-l4-007`, `tae-l6-002`). Con 4 rondas de investigación no
  alcanzó para completar el `required_facts` en esos tres.
- **¿Fallaron más por selección de evidencia que por presupuesto?** Sí, en
  proporción mayor: **6/17 son reconciliación** (D) y **2/17 evidencia
  mal dirigida** (C) — 8 de 17, casi la mitad, fallan por *qué se hizo con
  la evidencia ya obtenida* (metodología, fórmula, alcance), no por falta de
  tiempo para obtenerla.
- **¿Fallaron por reconciliación?** **6/17** (35%), y es la categoría más
  grande. Patrón dominante y accionable: preferir KPIs precomputados sobre
  recálculo manual (2 casos verificados con la misma causa exacta).
- **¿Riesgo de causalidad no soportada?** **2/17** explícitos (`tae-l4-004`,
  `tce-investigationanomaly-001`), ambos manejados con prudencia razonable
  (declaran incertidumbre en vez de inventar causa) — el riesgo se manifiesta
  como **score bajo por declinar apropiadamente**, no como alucinación de
  causalidad. Esto sugiere que el riesgo real no es que el modelo invente
  causalidad, sino que el grader determinístico no tiene forma de premiar una
  declinación bien razonada (ese es trabajo del judge, no implementado aún).

**Marcado explícitamente como incierto:** no puedo cuantificar cuántos turns
"pararon demasiado tarde" en el sentido de gastar rondas en evidencia ya
redundante — eso requeriría telemetría por ronda que el runtime actual no
persiste (ver limitación metodológica abajo).

## Limitación metodológica reconocida

`turns.jsonl` almacena `executed_sql`/`tool_calls` como listas planas
cronológicas, sin atribución de ronda por query. Un intento de agrupar por
`duration_ms` (que sí crece dentro de una ronda y resetea al inicio de la
siguiente) funcionó de forma consistente para F4 pero no para B27 — no se usó
para evitar fabricar precisión que los datos no sostienen. El análisis de los 2
casos regresados se apoyó en diferencias de *conjunto* de evidencia y en lectura
directa de texto/gates, no en atribución exacta por ronda.

## Qué debe aprender F4 de esto

### Campos de `AnalysisState` respaldados por evidencia observada

| Campo | Respaldo concreto |
|---|---|
| **`deliverable`** | Ninguno de los 17 casos falla por no entender la pregunta — todos interpretan correctamente el objetivo. Fijarlo temprano no habría cambiado ningún resultado observado aquí. **No hay evidencia directa que lo exija**, aunque tampoco lo contradice; se mantiene como hipótesis de diseño, no como hallazgo. |
| **`working_answer`** | Justificado indirectamente: la Etapa 1 ya demuestra que *tener siempre algo entregable* (vía síntesis reservada) es lo que rescató 17 turns. Un `working_answer` explícito que se actualice ronda a ronda formalizaría ese mecanismo, no lo reinventa. |
| **`evidence` con proveniencia** | **Fuertemente respaldado.** El caso `tae-l1-002`/`tce-followup-001` muestra que el modelo no distingue "dato que ya calculé yo mismo" de "dato canónico ya existente en el sistema" (`derived_kpi`). Un registro de evidencia que marque la *fuente* (KPI precomputado vs. agregación manual) habría hecho visible esa distinción al momento de decidir si seguir investigando. |
| **`open_material_gaps`** | **Respaldado.** Los 3 casos B (`tae-l2-003`, `tae-l4-007`, `tae-l6-002`) muestran al modelo declarando explícitamente, en prosa, qué le faltó ("no alcancé a recuperar los valores de LTV", "no pude verificar composición"). Ese conocimiento existe en la cabeza del modelo pero no está estructurado — formalizarlo es promover algo que el modelo ya hace informalmente, no imponer una capa nueva. |

### Campos que NO se recomiendan (sin respaldo en los datos)

- **`hypotheses` como estructura separada** — los 2 casos de causalidad no soportada (E) ya declinan responsablemente en prosa; no hay evidencia de que necesiten un campo de hipótesis explícito para hacerlo mejor. Sería ceremonia sin fallo que la justifique.
- **`assumptions` como campo de estado** — ninguno de los 17 casos falla por un supuesto no declarado; los que declinan ya explican sus supuestos en el texto. El rúbrico juzga el texto, no el estado.
- **Confidence score numérico por hecho** — ningún caso analizado se habría resuelto mejor con un número de confianza; el patrón dominante (D, reconciliación) es sobre *qué fuente usar*, no sobre *cuán seguro estar*.

### Qué debe quedar como runtime metadata (no en el state)

Confirmado por este análisis, no solo por diseño previo:

- **`budget`** — el mecanismo determinístico ya demostró funcionar (17→0) sin que el LLM necesite razonar sobre cuántas rondas le quedan como parte de su "estado de análisis"; es control del runtime, correctamente.
- **`action history` (SQL/tool_calls ejecutados)** — ya vive en `Turn.queries`/`tool_calls`, capturado por el sandbox, no autoreportado. Ningún hallazgo de este análisis sugiere que deba moverse al state.
- **`round count`** — igual que budget, es del runtime; el análisis de los 2 casos regresados confirma que el LLM no necesita saber "voy en ronda 3 de 4" para razonar bien, necesita saber "esto es lo que ya verifiqué" (eso es `evidence`, no `round count`).
- **`artifact registry`** — no aplica a esta etapa (Track B no produce artifacts no-textuales); no hay evidencia ni en contra ni a favor.

## Definición operacional: "material gap"

Derivada de los casos reales, no impuesta:

> Un gap es material cuando su resolución **cambiaría el número que el
> `primary_fact`/hecho requerido exige**, o **la fuente de ese número** (p.ej.
> "¿existe un valor ya calculado en el sistema que no he consultado?"), o
> **el desglose que la pregunta pide explícitamente** (por activo, por tipo, por
> fondo) cuando la respuesta actual solo da el agregado.

Evidencia que sostiene cada cláusula:
- "cambiaría el número exigido": `tae-l5-003` — el gap entre desglosar Apo4501
  vs reportar por tipo de unidad cambió el resultado del gate C1.
- "la fuente de ese número": `tae-l1-002`/`tce-followup-001` — el gap real no
  era falta de datos, era no haber consultado la fuente canónica existente.
- "el desglose que la pregunta pide": `tae-l6-002`, `tae-l4-007` — preguntas
  multi-tema donde la respuesta cubrió el tema pero no todos los sub-hechos
  pedidos.

No se propone score, threshold ni taxonomía cerrada — la cláusula "cambiaría X"
es deliberadamente evaluativa, para que el LLM la aplique caso a caso.

## Definición operacional: "sufficient evidence"

> La evidencia es suficiente para responder responsablemente cuando **cubre el
> hecho/los hechos que la pregunta pide de forma explícita o inferible**, **con
> la fuente más directa disponible** (canónica antes que recalculada), y
> cuando **cualquier incertidumbre restante puede declararse en la respuesta
> en vez de tener que resolverse**.

Evidencia que sostiene esto:
- Los 5 casos exitosos (A) — incluyendo dos que **declinan responsablemente**
  (`tae-l8-003`, y en menor medida `tae-l4-004`) — muestran que "suficiente"
  no significa "todo resuelto": significa que la incertidumbre restante fue
  reconocida en vez de rellenada con una suposición. `tae-l8-003` obtiene
  `completeness=1.0` declinando cuantificar CapEx, precisamente porque
  reconocer el límite de los datos *era* la respuesta correcta.
- Los 3 casos B muestran el contraste: no declinaron responsablemente, se
  quedaron a medio camino sin ni resolver ni declarar el gap con la misma
  claridad que los casos A.

Esta definición evita exigir certeza total (los casos A que declinan lo
demuestran) y evita premiar la exhaustividad (ningún caso exitoso usó más
rondas que los que fallaron; `tae-l4-003` con 11 SQL y `tae-l6-001` con 9 SQL
tienen éxito, pero también `tae-l8-003` con solo 5).

## Decisión

**KEEP Stage 1**, sin cambios. Las decisiones congeladas por el usuario
(mantener 4+1, no revertir, no excepciones para los 2 casos regresados) quedan
confirmadas por este diagnóstico: una de las dos regresiones es un artefacto de
grader, no de presupuesto; la otra es una elección de presentación en la
síntesis, no una pérdida clara de evidencia.

## Aprendizajes para las siguientes etapas

1. El mecanismo de síntesis reservada (Etapa 1) resuelve el problema de
   *no responder*. No resuelve el problema de *responder con la fuente/nivel
   de desglose equivocado* — ese es el problema dominante ahora (6/17
   reconciliación).
2. `AnalysisState` v1 debería priorizar **evidence con proveniencia de fuente**
   (canónica vs. derivada) por sobre objective/deliverable — es lo único con
   respaldo directo y repetido en los datos.
3. El riesgo de causalidad no soportada no se manifestó como alucinación en
   ningún caso observado — se manifestó como declinación correcta mal
   recompensada por un grader puramente determinístico. Relevante para cuándo
   se active el judge, no para el reasoning loop en sí.
4. Dos regresiones de 79 turns no ameritan revertir ni parchear — pero sí
   confirman que medir "evidencia perdida" requiere telemetría por ronda que
   hoy no existe, si se quiere auditar esto con más rigor en el futuro.
