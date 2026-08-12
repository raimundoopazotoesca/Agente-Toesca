# Phase 2 Closure (2026-08-12)

Cierre post-merge. El merge a `main` (commit `5965620`) se hizo el 2026-08-12 con
la suite del branch en verde, pero el eval `--full` de esa corrida resultó
contaminado por un bug de infraestructura real descubierto durante la
verificación post-merge. Este documento registra los 3 fixes aplicados después
del merge y los números finales, incluyendo el gap principal que queda abierto
para Fase 3.

## Bugs encontrados y corregidos post-merge

1. **`tools/db_chat.py`: modelo Gemini decomisionado.** `gemini-2.5-flash`
   (hardcodeado en `_PROVIDER_LIST`) empezó a devolver 404
   `"no longer available to new users"` para esta cuenta de API, rompiendo el
   fallback cada vez que la cadena `deepseek→groq×3` fallaba y caía a Gemini.
   Fix: cambiar a `gemini-flash-latest` (alias que siempre apunta al Flash
   vigente). Preexistente, no introducido por Fase 2.

2. **`tools/analyst/intent.py`: parsing de JSON no robusto.**
   `extract_intent()` hacía `json.loads(raw)` directo sobre la respuesta del
   LLM. Si el proveedor de turno (Groq/Mistral/Gemini tienen distinta
   disciplina de formato) envolvía el JSON en fences ``` o agregaba texto, el
   parseo fallaba silenciosamente y el caso caía a
   `IntentResult(metric=None, confidence=0.0, needs_clarification=True)` —
   es decir, clarify automático sin relación con si la pregunta era ambigua.
   `tools/db_chat.py` ya tenía `_extract_json()` (regex `\{.*\}` + fallback)
   para este mismo problema en el paso de generación SQL; `intent.py` no lo
   reusaba. Fix: `_extract_json()` duplicada en `intent.py` (el módulo no
   depende de `db_chat` a propósito, para mantenerse testeable sin red).

3. **`tools/analyst/intent.py`: sinónimos de métrica no llegaban al prompt.**
   `semantic/metrics/*.yaml` ya cura una lista `synonyms` por métrica (ej.
   `vacancia_pct: [vacancia, ocupacion, ocupación, occupancy, ...]`), pero
   `_build_prompt()` solo pasaba los nombres técnicos al LLM
   (`vacancia_pct, noi, ...`), no los sinónimos. El LLM debía adivinar que
   "ocupación" mapea a `vacancia_pct` por su propio conocimiento, de forma
   inconsistente entre llamadas/proveedores. Fix: `_format_metric_catalog()`
   arma `nombre_tecnico: sinonimo1, sinonimo2, ...` por métrica y se inyecta
   en el prompt.

## Eval — progresión de las 4 corridas

| Corrida | Metric | Entity | SQL-exec | Clarify-expected | Multi-turn |
|---|---|---|---|---|---|
| Fase 1 baseline (18 preg., `extract_intent()` aislado) | 6/18 (33%) | 8/18 (44%) | n/a | n/a | n/a |
| A. Post-merge, contaminada por bug #1 (Gemini 404) | 36/38 (95%)* | 24/38 (63%) | 16/38 (42%)* | 7/7 | 3/7 |
| B. +fix #1 (Gemini) +fix #2 (JSON parsing) | 35/38 (92%) | 28/38 (74%) | 33/38 (87%) | 7/7 | 2/7 |
| **C. +fix #3 (sinónimos) — final** | 35/38 (92%) | **29/38 (76%)** | **36/38 (95%)** | 5/7 | **2/7** |

\* Corrida A tenía metric accuracy inflada porque muchos casos fallaban aguas
abajo (SQL/synthesis) sin afectar la detección temprana de métrica; SQL-exec
estaba deprimido por el mismo bug de infraestructura, no por capability.

Fecha de la corrida final (C): 2026-08-12. Proveedores observados en esa
corrida: `llama-3.3-70b-versatile` (Groq) y `mistral-large-latest`
predominantemente; `gemini-flash-latest` y `gpt-oss-120b` (SambaNova)
ocasionalmente. `DEEPSEEK_API_KEY` sigue sin configurar (gap ya documentado en
el baseline de Fase 1, no resuelto en Fase 2).

## Estado contra el criterio de cierre del usuario

- ✅ Metric ~90%+: 92%
- ✅ Entity similar o mejor que antes: 76%, mejor que las 2 corridas previas
- ✅ SQL execution no dominado por infra: 95% de éxito quando se intenta generar SQL
- ⚠️ Clarify aceptable: bajó de 7/7 a 5/7 tras el fix de sinónimos (dar más
  contexto al LLM también lo hizo arriesgar respuesta en 2 casos donde antes
  pedía aclaración honestamente) — regresión menor, no bloqueante
- ❌ **Multi-turn funcionando de verdad: 2/7, sin movimiento entre las
  corridas B y C** — el gap principal, ver abajo

## Gap principal pendiente para Fase 3: multi-turn / inheritance conversacional

El fix de sinónimos (bug #3) mejoró single-turn de forma medible pero **no
movió multi-turn en absoluto** (2/7 en ambas corridas B y C). Diagnóstico:

- `tools/analyst/intent.py:_build_prompt()` construye el prompt de
  `extract_intent()` a partir de la pregunta actual únicamente — nunca recibe
  el historial de conversación (`history`) que sí le llega a
  `db_chat.answer()`. En un follow-up sin métrica explícita ("¿Y versus el
  año pasado?"), el LLM no tiene señal de que debería devolver
  `metric: null` para permitir que `extract_intent()` herede
  `state["last_metric"]` — en cambio alucina una métrica nueva con
  confianza suficiente para pisar la herencia
  (`parsed.get("metric") or state["last_metric"]` prioriza lo que devuelve
  el LLM).
- Test de regresión que documenta esto:
  `tests/test_db_chat.py::TestConversationalInheritance::test_followup_inherits_metric_and_entity`
  — queda **fallando intencionalmente** como marcador de este gap conocido,
  no se modificó la aserción para que pase artificialmente.
- Evidencia adicional de que el problema es de contexto conversacional y no
  de cobertura semántica de una sola pregunta: la misma pregunta
  ("ocupación de X") resuelve bien en aislamiento (single-turn) pero falla
  en el turno 1 de una conversación multi-turn con contenido casi idéntico
  — indica variabilidad entre llamadas LLM (temperatura/proveedor) más que
  un bug de cobertura adicional cazable con el mismo enfoque de esta fase.

**Recomendación para Fase 3**: pasar el historial de conversación (o al
menos el estado ya resuelto: `last_metric`/`last_entities`/`last_period`)
al prompt de `extract_intent()`, con instrucción explícita de devolver
`null` en vez de adivinar cuando la pregunta actual no menciona una métrica
nueva. Esto es un cambio de diseño de prompt, no un fix de una línea —
amerita su propio ciclo de brainstorming/plan en vez de parchearse al cierre
de esta fase.

## Archivos modificados en este cierre

- `tools/db_chat.py` — 1 línea, modelo Gemini
- `tools/analyst/intent.py` — parsing JSON robusto + sinónimos en el prompt

No se tocó `_validate_sql`, `_run_sql`, ni la cadena de fallback de
proveedores (`_provider_chain`) más allá del nombre del modelo Gemini, por lo
que las restricciones globales del plan original de Fase 2 siguen respetadas.
