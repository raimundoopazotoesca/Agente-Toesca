# Analyst Agent — Fase 3: Conversational Intelligence — Design

## Contexto

Fase 2 cerró con: metric accuracy 35/38 (92%), entity accuracy 29/38 (76%), SQL execution 36/38 (95%), clarify-when-expected 5/7, **multi-turn 2/7**. Multi-turn es el cuello de botella claro de esta fase.

## Diagnóstico (por qué multi-turn está en 2/7)

Hoy (`tools/analyst/intent.py`, `conversation_state.py`):

- `extract_intent()` construye el prompt de intent extraction con **solo la pregunta actual + catálogo de métricas** — nunca ve el historial ni el state. El LLM que interpreta "¿Y versus el año pasado?" no sabe de qué se viene hablando.
- El "multi-turn" que funciona hoy es un accidente del fallback mecánico `parsed.get(x) or state["last_x"]`: si el LLM (ciego al contexto) deja un campo en null, se reinyecta el valor anterior.
- Esto se rompe en varios casos reales:
  - **Topic reset no se detecta**: una pregunta nueva sin métrica clara hereda igual el `last_metric` del turno anterior porque el fallback es incondicional.
  - **No existe `grouping`/`analysis_mode`**: "hazlo mensual" no tiene dónde aterrizar en `IntentResult`.
  - **`comparison` no persiste con criterio**: se guarda en `last_analysis_type` pero nunca se lee de vuelta (dead field).
  - **Reemplazo de entidad es todo-o-nada por dict completo**, no por campo.
  - **`confidence` no es señal útil para follow-ups**: el LLM la calcula sin contexto conversacional.
  - **No hay detección de corrección** ("no, me refería a...") — funciona solo si el LLM extrae bien la entidad nueva por casualidad.
  - **Sin trazabilidad de origen** por campo — imposible depurar por qué el sistema decidió lo que decidió.

Conclusión: hay merge mecánico de 4 campos, pero cero razonamiento conversacional. "Entender" continuidad/reemplazo/corrección/reset no existe como concepto.

## Principio arquitectónico

Semantic layer, intent/entity resolution, verified queries y conversation state son **contexto asesor** para el Analyst Agent — nunca un árbol de decisión cerrado. `metric=null` y goals exploratorios (`investigate_recent_anomalies`, etc.) son resultados válidos. El catálogo semántico define qué está oficialmente gobernado, **no limita qué puede investigar el agente**.

Separación de responsabilidades:
- **Understanding layer** (controlada): entidades, fechas, sinónimos, referencias, correcciones, contexto conversacional.
- **Analytical reasoning** (flexible, fuera de alcance de esta fase): qué investigar, qué comparar, qué concluir.

## Diseño

### 1. Schema de estado

```python
@dataclass
class ResolvedValue:
    raw_value: Any
    canonical_value: Any | None
    resolution_status: str  # "resolved" | "unresolved" | "ambiguous"
    source: str              # "explicit" | "inherited" | "inferred" — proveniencia, no confianza

@dataclass
class ConversationState:
    active_goal: ResolvedValue | None = None
    analysis_mode: ResolvedValue | None = None   # string abierto: exploratory, comparison, trend, ...
    entities: dict[str, ResolvedValue] = field(default_factory=dict)  # "fondo", "activo"
    metrics: list[ResolvedValue] = field(default_factory=list)
    period: ResolvedValue | None = None
    comparison: ResolvedValue | None = None
    grouping: ResolvedValue | None = None
    output_request: ResolvedValue | None = None
```

Reglas clave:
- `raw_value` siempre se conserva, incluso si no resuelve a nada canónico — el catálogo no es whitelist. Una métrica no catalogada (ej. "concentración de renta") queda con `canonical_value=None, resolution_status="unresolved"` y el Analyst Agent la recibe igual para poder explorar cómo obtenerla.
- `source` es proveniencia pura (explicit/inherited/inferred), nunca confianza. Un valor `explicit` puede seguir `unresolved` si el usuario lo dijo claro pero no mapea a nada conocido.
- `resolution_status="ambiguous"` cuando el catálogo/entity_resolver encuentra más de un candidato plausible.

Persistencia: mismo mecanismo de hoy — `OrderedDict[session_id, ConversationState]`, cap 500 sesiones, eviction LRU. Solo cambia la forma del valor guardado (antes dict de 4 campos, ahora `ConversationState`).

### 2. LLM de conversational understanding

Un único LLM call por turno (`tools/analyst/conversation_understanding.py`), reemplaza `extract_intent`. Recibe:
- El `ConversationState` actual serializado compacto (YAML o JSON legible).
- Los últimos 2-3 turnos crudos (role+content truncado) — respaldo para nuance lingüística que el state no captura, sin pasar el historial completo.
- La pregunta actual.

Responsabilidad exclusiva: entender la conversación. No resuelve entidades contra catálogo ni valida métricas — eso lo hace el código después.

Devuelve JSON:

```json
{
  "turn_relation": "continue | modify | correct | new_topic",
  "delta": [
    {"field": "metrics", "operation": "replace", "raw_value": "concentración de renta", "source": "explicit"},
    {"field": "entities.activo", "operation": "keep"}
  ]
}
```

- `field` ∈ `active_goal, analysis_mode, entities.fondo, entities.activo, metrics, period, comparison, grouping, output_request`.
- `operation` ∈ `keep, replace, clear, infer`.
- `turn_relation` describe exclusivamente cómo se relaciona el turno con el estado anterior, para la semántica del merge — no es un intent de negocio ni dirige qué herramientas usa el Analyst Agent.
- El LLM nunca produce `canonical_value`/`resolution_status` — eso es responsabilidad del código.

### 3. Merge determinístico (`apply_delta`)

Por cada dimensión del schema:

1. Si aparece en `delta` → aplica la operación indicada.
2. Si está omitida:
   - `turn_relation ∈ {continue, modify, correct}` → `keep` (política de seguridad para follow-ups).
   - `turn_relation == "new_topic"` → `clear`, salvo que el LLM haya indicado `keep` explícitamente para esa dimensión. Esto evita que una pregunta nueva sin relación herede `metric`/`grouping` del análisis anterior — el bug central que produce el 2/7 actual.
3. `replace` / `infer` → resuelve `raw_value` contra catálogo semántico (`metrics`) o `entity_resolver` (`entities`), produce `canonical_value` + `resolution_status`; `source="explicit"` para `replace`, `source="inferred"` para `infer`.
4. `keep` → conserva el `ResolvedValue` anterior completo, sin re-resolver.
5. `clear` → campo vuelve a `None` / lista vacía.

Código valida el JSON del LLM antes de aplicar (campos desconocidos ignorados con log, `operation` inválida tratada como `keep` conservador).

### 4. `ambiguity.py` — nueva lógica de clarify

Pregunta rectora: **¿hay suficiente contexto para intentar resolver el objetivo sin tomar una decisión arbitraria de alto impacto?** — no "¿hay algún campo poblado?".

Fuerzan `clarify` aunque haya campos poblados:
- Alguna dimensión relevante (`entities`, `metrics`) con `resolution_status="ambiguous"` (múltiples candidatos plausibles, ej. "renta" mapea a >1 métrica).
- `metrics` explícitas pero todas `unresolved`, y no hay `active_goal`/`analysis_mode` exploratorio que permita investigar igual.
- Contradicción entre `turn_relation="correct"` y un valor nuevo que no logra resolverse a nada usable.

Permiten `proceed` aunque falten métricas:
- `analysis_mode="exploratory"` o `active_goal` con intención clara, aunque `metrics=[]`.
- `entities` con `canonical_value` resuelto, aunque `metrics` esté vacío.

Se mantiene intacta la lógica existente de `verified_hint`/`has_history` como señales adicionales de grounding.

### 5. Integración

- **`context_builder.py`**: `build_context()` llama `understand_conversation(...)` en vez de `extract_intent(...)`. `_build_sections` se adapta para leer `ResolvedValue` (mostrando `resolution_status` cuando es `unresolved`/`ambiguous`, para que el LLM de SQL sepa que debe explorar y no asumir).
- **`db_chat.py`**: `answer()` mantiene su contrato externo. Se elimina la llamada manual a `update_state(...)` al final ([db_chat.py:1070](../../../tools/db_chat.py#L1070)) — el estado ya queda persistido dentro de `understand_conversation`.
- **`conversation_state.py`**: se reescribe para guardar `ConversationState` en vez del dict de 4 campos. Mismo `OrderedDict` + cap 500 + scoping por `session_id` (garantiza que `session_isolation_control` siga pasando).
- **`intent.py`**: se retira. Su lógica se reparte entre `conversation_understanding.py` (prompt + parsing del delta) y `apply_delta` (merge). `test_intent.py` se reemplaza por tests del nuevo módulo.
- **SQL pipeline**: sin cambios — validation, read-only, SELECT-only, fallbacks y verified-query behavior se mantienen intactos. Solo cambia qué contexto llega al pipeline.

### 6. Eval suite ampliada

`tests/eval/conversations.yaml` pasa de 4 a 8 escenarios, cubriendo: inheritance, entity replacement, metric replacement, period replacement, grouping replacement, correction, new topic, exploratory (según brief §13). `session_isolation_control` se mantiene.

`run_eval.py` gana modo `--stability N` (default 5): corre cada conversación N veces y reporta pass-rate por escenario, distinguiendo:
- **Stochastic failure**: mezcla pass/fail entre corridas.
- **Architectural failure**: 0/N consistente.

### 7. Observabilidad

Log estructurado por turno (no expuesto al usuario, solo en logs/traces de modo eval y debug):

```
conversation_id, current_question, previous_state, turn_relation,
delta, new_state, explicit_fields, inherited_fields, inferred_fields,
clarification_reason, sql/context generated
```

## Fuera de alcance (explícito)

Multi-agent, vector DB, RAG avanzado, sandbox analítico Python, gráficos inteligentes, rediseño de Excel, loops autónomos de investigación multi-query, critic agents, cientos de intents nuevos, verified queries ad-hoc para tapar fallos puntuales de tests.

## Criterio de éxito

- Multi-turn: de 2/7 a >85-90% en la suite ampliada (8 escenarios × 5 runs).
- Metric accuracy y SQL execution se mantienen >90%.
- Entity accuracy mejora si es posible, sin sacrificar comportamiento abierto (`unresolved` como resultado válido) solo para inflar la métrica.
- Clarify-when-expected vuelve a nivel alto sin volverse excesivamente conservador (no debe bloquear preguntas exploratorias por falta de métrica).
- Session isolation determinística, verificada con test dedicado.
- No regresión relevante en single-turn.
