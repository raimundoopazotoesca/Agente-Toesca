# Toesca Analyst Benchmark v1 — Diseño

Estado: **propuesta de diseño para revisión**. No hay casos escritos todavía.
Rama: `feat/toesca-analyst-benchmark-v1`. Independiente de `feat/analyst-agent-phase3`.

Pregunta que gobierna todo el documento:

> ¿Esto mide qué tan buen analista es el sistema, o mide qué tan parecido es a `tools/analyst/`?

---

## 0. Resumen ejecutivo

Dos benchmarks separados, nunca fusionados en un número:

| | Casos v1 | Qué mide |
|---|---|---|
| **Toesca Conversation Eval** (TCE) | 24 conversaciones (~70 turnos) | Si la conversación se siente natural y confiable |
| **Toesca Analyst Eval** (TAE) | 48 tareas | Si el sistema trabaja como analista |

Ambos corren contra un **snapshot congelado** de la DB, vía un **contrato de adapter** que no sabe nada de la arquitectura interna. Scoring por **10 dimensiones** + **8 hard gates**. Grading **híbrido**: determinista donde se puede verificar, rúbrica con LLM-judge ciego donde no, calibración humana periódica sobre una muestra.

Split **dev (70%) / holdout (30%)**, el holdout cifrado-por-convención (no en prompts, no en few-shots, no en verified_queries).

---

## 1. Qué datos reales tenemos para construir ground truth

Inspección de `memory/agente_toesca_v2.db` (main, commit `c9b1dd5`).

### 1.1 Entidades confirmadas

**Fondos** (`dim_fondo`, 3): `TRI` (madre), `PT` (33,33% de TRI), `Apo` (30% de TRI).

**Activos** (`dim_activo`, 17):

| activo_key | fondo | categoría | nota |
|---|---|---|---|
| Torre A, Boulevard, Parking PT | PT | Oficinas / Oficinas / Parking | |
| Apo4501, Apo4700 | Apo | Oficinas | |
| Apo3001 | **TRI** | Oficinas | trampa clásica: *no* es del fondo Apo |
| Sucden | TRI | Industrial | Bodegas Maipú |
| Viña Centro, Mall Curicó | TRI | Centros Comerciales | |
| INMOSA + 6 residencias | TRI | Residencias | INMOSA es el agregado |
| Strip Machalí | TRI | Comercial | `vigente_hasta = 2025-08` (desinvertido) |

Además existen dos claves agregadas legacy en `derived_kpi`/`raw_vacancia_manual`: `Fondo Apoquindo` (= Apo4501+Apo4700) y `PT_consolidado`. Son **fuente de casos de ambigüedad**, no errores a esconder.

### 1.2 Cobertura temporal por fuente (lo que habilita o bloquea casos)

| Fuente | Rango | Períodos | Habilita |
|---|---|---|---|
| `raw_er_activo_line` | 2018-01 → 2026-08 | 104 | NOI, ingresos, gastos, diagnóstico de deterioro, series largas |
| `raw_vacancia_manual` | 2017-06 → 2026-12 | 115 | ocupación/vacancia histórica por activo y tipo de unidad |
| `raw_eeff_line` | 2017-01 → 2026-03 | 105 | balance/EERR fondo, patrimonio |
| `raw_ocupacion_residencia_line` | 2013-03 → 2026-03 | 157 | ocupación INMOSA por residencia |
| `derived_kpi` | 14.599 filas, 37 KPIs | | LTV, DSCR, TIR, DY, duration, perfil de vencimiento, cap rate |
| `raw_saldo_deuda`, `dim_credito` | 2.764 / 17 | | deuda, duration, refinanciamientos |
| `raw_valor_cuota_*`, `raw_dividendo`, `raw_ar_event` | 518/212/53 | | rentabilidad serie, dividend yield, TIR |
| `raw_parking_*` | 1.979 filas | | Parking PT: tickets, abonados, resultado UF |
| `raw_mercado_*` | ~350 filas | | benchmarks de mercado (oficinas, bodegas, comercio) |
| **`raw_rent_roll_line`** | **2026-05 → 2026-06** | **2** | ⚠️ ver abajo |
| `raw_movimiento_contrato` | 831 filas, sin `periodo` | | absorción vía `v_absorcion_*` |

### 1.3 Limitación crítica: rent roll

El rent roll normalizado tiene **solo dos períodos**. Consecuencia directa:

- **Sí podemos** preguntar por arrendatarios, m², renta UF y vencimientos **en 2026-05/2026-06** y por perfil de vencimiento (vía `derived_kpi.perfil_vencimiento`, 1.236 filas).
- **No podemos** construir ground truth de *evolución histórica de arrendatarios*, *rotación de contratos por año*, ni *renta UF/m² por trimestre desde rent roll*. Cualquier caso así sería inventado.

Decisión: esos casos entran en el **Nivel 8 (insufficient information)** — el comportamiento correcto es que el sistema diga que no tiene la serie. No los escribimos como casos factuales.

### 1.4 Métricas con definición formal ya escrita

`semantic/metrics/`: `vacancia`, `noi`, `tir`, `dividend_yield`, `tasa_arriendo`. Todo lo demás (LTV, DSCR, duration, cap rate, absorción, parking) existe **como dato en `derived_kpi`/vistas** pero sin YAML semántico. Eso no impide usarlo como ground truth (el número está y es reproducible), pero sí lo marca como zona donde una arquitectura con catálogo semántico y una sin él pueden divergir legítimamente — interesante para el benchmark, no un problema.

### 1.5 Zonas marcadas PENDING (no inventar)

Se registran en `eval/benchmark/PENDING.md` y no generan casos con `expected_value`:

- renta UF/m² desde rent roll (sin fórmula validada — ya anotado en los evals actuales)
- capex por activo (sin fuente normalizada)
- morosidad (no existe tabla; **el ejemplo "¿y la morosidad?" del brief solo puede ser un caso de Nivel 8**)
- serie histórica de arrendatarios/vencimientos (ver 1.3)
- `dscr` está en `derived_kpi` pero **no validado** contra CDG (memoria: "dscr NO validado") → solo casos cualitativos, nunca `expected_value`

### 1.6 Capacidades de artefactos hoy

- Gráficos: `db_chat` emite un bloque ```chart``` en markdown. Existe.
- Tablas: markdown. Existe.
- **Excel: no existe** en el camino del analista (`excel_tools.py` es del flujo CDG, no del chat).

Decisión: los casos de Nivel 7 incluyen Excel de todos modos, porque el benchmark mide el **producto deseado**, no la implementación actual. Se marcan `capability: xlsx_export` para poder reportar "0/4 en Excel porque ninguna arquitectura lo soporta aún" sin contaminar el resto del score.

---

## 2. Por qué no extendemos `tests/eval/`

Lo existente (`tests/eval/questions.yaml`, 45 preguntas; `conversations.yaml`, 4) puntúa **metric accuracy / entity accuracy / clarify rate**, leyendo `conversation_state` interno. Eso es un test de `tools/analyst/intent.py`, no un benchmark de analista: una arquitectura frontier-simple que responde perfectamente pero no expone `last_metric` sacaría 0.

Se conserva intacto. El nuevo benchmark vive en `eval/benchmark/` y **solo mira lo que el usuario vería**: la respuesta, los artefactos, y la traza de herramientas.

Sí reutilizamos como *insumo*: los aliases de `semantic/synonyms.yaml`, las trampas conocidas (Apo3001, "Apoquindo a secas", vacancia >100%) y los casos donde el sistema actual falla.

---

## 3. Contrato de ejecución (architecture-neutral)

Único punto de acoplamiento. Un adapter implementa:

```python
class BenchmarkAdapter(Protocol):
    def new_session(self, session_id: str) -> Session: ...

class Session(Protocol):
    def ask(self, message: str) -> Turn: ...
```

```python
@dataclass
class Turn:
    text: str                      # respuesta visible al usuario (markdown)
    artifacts: list[Artifact]      # {kind: table|chart|xlsx|file, path|payload, spec}
    tool_calls: list[ToolCall]     # {name, args, ok, duration_ms}
    queries: list[str]             # SQL realmente ejecutado contra el snapshot (capturado por el sandbox, no auto-reportado)
    asked_clarification: bool      # derivado del texto por el grader, no auto-declarado
    usage: Usage                   # {provider, model, calls, input_tokens, output_tokens, retries, latency_ms}
```

Reglas que preservan la neutralidad:

1. **`queries` lo captura el sandbox de DB, no el sistema evaluado.** El snapshot se abre a través de un wrapper que registra cada sentencia. Un adapter no puede "mentir" ni ser premiado por reportar bien.
2. **`asked_clarification` lo decide el grader** leyendo el texto. La Arquitectura A tiene un flag `clarify`; la B no. Usar el flag daría ventaja a A.
3. Ningún grader lee estado interno (`conversation_state`, `intent`, candidatos). Si un dato no es visible para un humano usando el producto, no se puntúa.
4. `tool_calls` es opcional: si un adapter no instrumenta herramientas, los casos con `tool_requirements` se marcan `unscored`, no `fail`. Se reporta la cobertura.

Adapters v1: `adapters/track_a_structured.py` (envuelve `db_chat.answer`), `adapters/track_b_frontier.py` (modelo + herramientas + contexto semántico, sin lógica compensatoria). Ambos fuera de `tools/` — **cero cambios en runtime productivo**.

---

## 4. Snapshot reproducible

Requisito: mismos números dentro de meses, aunque la DB productiva cambie.

**Estrategia elegida: snapshot pinneado por commit + materialización read-only.**

`memory/agente_toesca_v2.db` ya está versionada en git. Entonces:

```
eval/benchmark/snapshot.lock      # {git_sha, sha256, built_at, row_counts por tabla}
eval/benchmark/build_snapshot.py  # git show <sha>:memory/... > .cache/bench.db, verifica sha256, abre read-only
```

Por qué esto y no las alternativas:

- *Copiar la DB al repo*: +32 MB duplicados por cada re-pin. Descartado.
- *Fixture curado/sintético*: rompe el realismo y obliga a re-derivar ground truth a mano. Descartado para v1.
- *DB productiva en vivo*: imposible comparar modelos en el tiempo. Descartado explícitamente por el brief.
- *Pin por commit*: costo cero de almacenamiento, verificable por hash, y el snapshot es exactamente el mundo real en una fecha. **Elegido.**

Detalles:

- **Fecha congelada**: el snapshot fija `BENCHMARK_TODAY = 2026-08-13`. Todo "este año", "el mes pasado", "últimos 3 meses" se resuelve contra esa fecha, inyectada al adapter. Sin esto, los casos relativos se pudren solos.
- **Acceso read-only** (`file:...?mode=ro`) + wrapper que registra queries y aborta DDL/DML. Sirve también al hard gate de seguridad de DB.
- **Sin datos sensibles adicionales**: no se copia nada que no esté ya en la DB versionada.
- Re-pin del snapshot ⇒ re-validación de todos los `expected_value` mediante `verify_ground_truth.py` (§8.1), y bump de `benchmark_version`.

---

## 5. Categorías y número de casos

### 5.1 Toesca Conversation Eval — 24 conversaciones

| Categoría | Convs | Turnos aprox |
|---|---|---|
| Simple follow-up | 3 | 6 |
| Entity replacement | 3 | 7 |
| Metric replacement | 2 | 4 |
| Period replacement | 2 | 5 |
| Grouping / output change | 2 | 6 |
| Corrections (incl. corrección tardía) | 3 | 9 |
| Topic reset + retorno al tema anterior | 2 | 8 |
| Pronombres y referencias ("el segundo", "esa diferencia") | 2 | 6 |
| Exploratory continuation | 2 | 7 |
| Ambigüedad (4 sabores, ver abajo) | 3 | 8 |
| **Total** | **24** | **~66** |

Los 4 sabores de ambigüedad, uno por caso mínimo:
1. **corresponde preguntar** — "vacancia de Apoquindo" (fondo Apo vs activo agregado vs Apo3001)
2. **NO corresponde preguntar** — "ocupación de PT en junio" (unívoco; preguntar es fricción y penaliza)
3. **puede inferir razonablemente** — "¿cómo viene Curicó?" (único activo con ese nombre; inferir período = último disponible es correcto si lo declara)
4. **elegir arbitrariamente es peligroso** — "TIR de TRI" (contable vs bursátil dan números distintos y ambos existen) → elegir en silencio es hard gate.

Más un control de **session isolation**: dos sesiones en paralelo, la segunda pregunta "¿y el mes anterior?" sin contexto propio. Filtrar contexto de la otra sesión es hard gate.

### 5.2 Toesca Analyst Eval — 48 tareas

| Nivel | Tareas | Tier | Notas |
|---|---|---|---|
| L1 Retrieval factual | 10 | L1 | `expected_value` con tolerancia |
| L2 Comparación | 8 | L2 | valores + interpretación de la diferencia |
| L3 Analytical summary | 6 | L3 | "¿cómo viene X?" — el sistema elige qué es relevante |
| L4 Diagnosis | 7 | L3–L4 | required_behavior, no expected_sql |
| L5 Investigation / agentic | 6 | L4 | plan→consultar→profundizar→concluir |
| L6 Decision support | 4 | L4 | recomendación respaldada |
| L7 Artifacts | 4 | L2–L3 | tabla, gráfico, Excel×2 (`capability`-gated) |
| L8 Insufficient info | 3 | L2 | morosidad, activo inexistente, causalidad no observable |
| **Total** | **48** | | |

Anclas de dominio disponibles y reales para L4/L5 (no inventadas): la desinversión de **Strip Machalí** (2025-08), la brecha rent-roll, `Fondo Apoquindo` vs `Apo3001`, concentración de arrendatarios en el rent roll 2026-06, vacancia por tipo de unidad en PT/Apoquindo, y el comportamiento del parking PT.

Si al escribir los casos alguna categoría no alcanza sin inventar, **se entrega con menos casos y se documenta**, no se rellena.

---

## 6. Formato de caso

Un archivo YAML por caso, en `eval/benchmark/cases/{tce,tae}/`. Schema validado por test.

```yaml
id: tae-l4-007
suite: analyst           # analyst | conversation
level: L4                # L1..L8 (solo analyst)
tier: L4                 # L1..L4 dificultad, para routing
split: dev               # dev | holdout
capability: null         # p.ej. xlsx_export -> unscored si el track no la soporta

turns:
  - question: "¿Qué está explicando la caída de ingresos de Viña Centro?"

    # --- verificable determinísticamente ---
    required_facts:            # deben aparecer, con tolerancia
      - {ref: "vina_ingresos_2026_06", tolerance_pct: 1.0}
    acceptable_facts: [...]    # suman a completeness, no obligatorios
    expected_entities: {activo: "Viña Centro"}
    expected_period: {from: "2025-01", to: "2026-06"}
    forbidden_claims:
      - "atribuir la caída a vacancia sin mostrar la serie de vacancia"
      - "afirmar causalidad de un solo mes"
    tool_requirements:
      min_distinct_queries: 2
      must_touch_tables: [raw_er_activo_line]
    clarification_expected: false   # true | false | acceptable

    # --- evaluado por rúbrica ---
    expected_behavior:
      - establecer si la caída realmente ocurrió y en qué período
      - inspeccionar drivers (ingresos vs gastos, vacancia, un solo arrendatario)
      - distinguir hecho de hipótesis
    rubric_focus: [analytical_quality, grounding, investigation_quality]

    notes: "..."

ground_truth_refs:      # resueltos por SQL contra el snapshot, no hardcodeados
  vina_ingresos_2026_06:
    sql: "SELECT ... FROM raw_er_activo_line WHERE ..."
    unit: CLP
```

Punto clave: **los números no se escriben a mano**. `ground_truth_refs` guarda el SQL; `verify_ground_truth.py` lo ejecuta contra el snapshot y materializa `expected_values.json`. Si el snapshot se re-pinnea y un valor cambia, el test falla y obliga a revisar el caso. Es el SQL *del autor del caso*, nunca del sistema evaluado, y no se compara contra el SQL del sistema.

---

## 7. Scoring

Sin score único. Cada caso produce un vector de dimensiones en [0,1], solo las aplicables:

| Dimensión | Grader | Aplica a |
|---|---|---|
| `factual_correctness` | determinista | L1–L4, L7 |
| `completeness` | determinista + rúbrica | todos |
| `tool_correctness` | determinista | donde hay `tool_requirements` |
| `analytical_quality` | rúbrica | L2–L6 |
| `grounding` | híbrido (hechos citados ⊆ hechos ejecutados) | L3–L6 |
| `hallucination` | determinista + rúbrica (penalización, no premio) | todos |
| `conversational_quality` | rúbrica + determinista (entidad/período heredados) | TCE |
| `clarification_judgment` | determinista (vs `clarification_expected`) | TCE ambigüedad, L8 |
| `investigation_quality` | rúbrica + señal de `queries` | L4–L6 |
| `output_usefulness` | rúbrica | todos |

**Reporte**: matriz `track × modelo × tier × dimensión`. Los agregados permitidos son promedios *por dimensión* y *por tier*. Un "Toesca score" único, si alguna vez hace falta, se calcula al final con pesos explícitos y versionados — nunca antes de mirar la matriz.

---

## 8. Hard gates

Un gate no resta puntos: **anula el caso** (todas las dimensiones → 0) y se cuenta aparte en `gate_violations`. Un track con estilo excelente y un gate disparado no puede ganar.

| Gate | Detección |
|---|---|
| `G1 wrong_number` | dato financiero/operacional fuera de tolerancia vs ground truth | determinista |
| `G2 fabrication` | cifra/entidad/hecho en la respuesta que no aparece en ningún resultado de query ejecutada | determinista + judge |
| `G3 entity_confusion` | responde de otro activo/fondo (el clásico Apo3001 → fondo Apo) | determinista |
| `G4 wrong_period` | período distinto al pedido/heredado sin declararlo | determinista |
| `G5 unsupported_causality` | afirma causa sin evidencia consultada | judge con evidencia de `queries` |
| `G6 session_leak` | menciona entidad/dato que solo existe en otra sesión | determinista |
| `G7 unsafe_db` | intento de DDL/DML/PRAGMA/attach, o lectura fuera del snapshot | wrapper de DB |
| `G8 ignored_correction` | tras "no, me refería a X", sigue respondiendo Y | determinista (entidad del turno siguiente) |

Seis de ocho son deterministas. Solo G5 requiere judge, y con la evidencia a la vista.

---

## 9. Estrategia de grading

Tres capas, en este orden:

**1. Deterministic graders** (siempre, primero, baratos). Valores con tolerancia relativa configurable por unidad (default: 0,5% CLP/UF, 0,1 pp para porcentajes); entidades y períodos por normalización contra `semantic/`; tablas/archivos/queries ejecutadas; presencia de `required_facts`; ausencia de números no soportados; session isolation. Si un gate determinista dispara, **no se llama al judge** (ahorro y evita que el judge "rescate" una respuesta incorrecta con buena prosa).

**2. Rubric judge** (LLM), solo para lo genuinamente subjetivo. Recibe: pregunta, respuesta, **los hechos verificados y las queries ejecutadas**, y la rúbrica del caso. No recibe: identidad del modelo/track, ni la respuesta "de referencia" de otro sistema. Puntúa cada dimensión 0–4 con anclas escritas y exige una justificación citando la respuesta.

**3. Calibración humana** (periódica, no continua). Muestra estratificada del 15% de los casos por ronda, revisada a ciegas por una persona. Se mide correlación judge↔humano (Spearman) y desacuerdos >1 punto. Si la correlación cae bajo un umbral acordado, la rúbrica se corrige antes de aceptar resultados. Los casos L5/L6 con desacuerdo persistente se marcan `human_only`.

### 9.1 Anti-sesgo del judge

Riesgos documentados y su mitigación:

- **Self-preference** (un judge favorece salidas de su propia familia de modelos) → judge de familia distinta a los modelos evaluados cuando sea posible; si no, doble judge y reportar la discrepancia.
- **Identidad del track** → respuestas anonimizadas, sin firmas de formato (se normaliza whitespace y encabezados obvios).
- **Sesgo de orden/posición** en comparaciones pareadas → orden randomizado por caso, semilla registrada.
- **Verbosidad = calidad** → la rúbrica separa explícitamente `output_usefulness` (¿sirve?) de estilo; se registra largo de respuesta como covariable para detectar la correlación.
- **Estilo rescatando correctness** → correctness ya se decidió en la capa 1; el judge no puede subirla.
- **Deriva del judge** → judge pinneado (modelo + versión + temperature 0) en `judge.lock`; cambiarlo obliga a re-correr la calibración.

---

## 10. Dev vs holdout

- **dev = 70%** (17 TCE + 34 TAE), **holdout = 30%** (7 TCE + 14 TAE), estratificado por categoría y tier.
- El holdout vive en `eval/benchmark/cases/holdout/` con un `README` que dice qué está prohibido, y se corre **solo en hitos de decisión** (elegir modelo, elegir arquitectura, aprobar routing), no en el ciclo de tuning.
- Regla operativa: el texto de los casos holdout **no puede aparecer** en system prompts, few-shots, `tools/analyst/verified_queries/`, `semantic/synonyms.yaml` ni en tests funcionales. Un test del benchmark (`test_holdout_not_leaked.py`) hace grep de n-gramas de las preguntas holdout sobre esos archivos y falla si hay coincidencia.
- Cada corrida del holdout se registra con fecha y motivo. Correrlo más de ~1 vez por hito lo degrada a dev; eso se documenta, no se prohíbe informalmente.

---

## 11. Cómo comparar modelos (costo/latencia y routing)

Cada `Turn` acumula `usage`. Pricing **no hardcodeado**: `eval/benchmark/pricing.yaml` con `{provider, model, input_per_mtok, output_per_mtok, source_url, fetched_at}`, cargado en runtime. Si un modelo no tiene entrada, el costo se reporta como `unknown`, no como 0.

Métricas reportadas: costo/caso, latencia p50/p95, tool calls por caso, retries, y la métrica que realmente importa:

```
useful analyst work / dollar  =  Σ(score_dimensional ponderado de casos sin gate) / Σ(costo)
```

Se reporta **por tier**, que es exactamente lo que decide el routing: si un modelo económico empata en L1/L2 y colapsa en L3/L4, la tabla lo muestra directamente y justifica `cheap→L1/L2, frontier→L3/L4`. El benchmark también permite evaluar el router mismo, tratándolo como un track más.

---

## 12. Cómo comparar arquitecturas

Track A (estructurada) y Track B (frontier-simple) se registran en `tracks.yaml` y comparten:
mismo snapshot, misma fecha congelada, mismos casos, mismos graders, mismo judge.

Lo que **no** se comparte y por eso no se puntúa: prompts internos, catálogo semántico, estrategia de resolución de entidades, presencia o ausencia de state. Son la variable independiente.

Reporte de decisión: matriz por tier y dimensión, más costo. La pregunta "¿cuánto de F1–F3 conservar?" se responde ablacionando Track A (p.ej. A sin candidate extraction, A sin state) como tracks adicionales contra el mismo benchmark.

---

## 13. Qué se automatiza y qué requiere humano

| Automatizable hoy | Requiere revisión humana |
|---|---|
| Ejecución de casos y captura de traza | Redacción de `required_facts` / `forbidden_claims` |
| Todos los graders deterministas | 6 de 8 gates son automáticos; G5 necesita spot-check |
| 6 de 8 hard gates | Casos L5/L6 marcados `human_only` |
| Materialización de ground truth por SQL | Aprobar el re-pin del snapshot cuando cambian valores |
| Costo, latencia, tokens | Calibración del judge (15% por ronda) |
| Test anti-leak del holdout | Decidir si un caso pasa a PENDING por falta de datos |

Estimación honesta: ~75% del scoring corre solo; el 25% restante es donde está el valor real y no conviene automatizarlo.

---

## 14. Estructura de archivos propuesta

```
eval/benchmark/
  README.md
  DESIGN.md -> docs/toesca-analyst-benchmark-v1-design.md
  PENDING.md                # zonas sin datos, no inventar
  snapshot.lock  build_snapshot.py  verify_ground_truth.py
  pricing.yaml  judge.lock  tracks.yaml
  schema/case.schema.json
  cases/tce/*.yaml  cases/tae/*.yaml  cases/holdout/*.yaml
  adapters/{base.py,track_a_structured.py,track_b_frontier.py}
  graders/{deterministic.py,gates.py,rubric_judge.py}
  runner.py  report.py
  tests/                    # tests del benchmark, no del agente
```

Nada dentro de `tools/`, `agent.py` ni `scripts/` cambia. `tests/eval/` se conserva tal cual.

---

## 15. Limitaciones conocidas de v1

1. Rent roll con 2 períodos → sin casos históricos de arrendatarios/vencimientos (§1.3).
2. Excel no existe en el camino del analista → 2 casos quedarán `unscored` hasta que exista la capacidad.
3. `dscr` no validado → sin `expected_value`.
4. El judge introduce varianza; sin calibración humana los scores L5/L6 son indicativos, no decisorios.
5. 48+24 casos no cubren todo el dominio; es un v1 deliberadamente pequeño y correcto.
6. La fecha congelada envejece: dentro de ~6 meses "este año" contra 2026-08-13 se sentirá artificial y habrá que re-pinnear (con re-validación completa).

---

## 16. Plan de implementación incremental (post-revisión)

1. `feat(eval): schema de caso + validación` (schema, tests, sin casos)
2. `feat(eval): snapshot pinneado + sandbox read-only de DB`
3. `feat(eval): contrato de adapter + Track A`
4. `feat(eval): graders deterministas + hard gates` (con tests propios)
5. `feat(eval): primeros 20 casos L1/L2 + TCE simple` — primera señal real
6. `feat(eval): rubric judge + anti-sesgo`
7. `feat(eval): casos L3–L8 y conversaciones complejas`
8. `feat(eval): reporte por tier + costo` y Track B

Cada etapa: tests verdes, diff revisado, cero cambios de comportamiento productivo.
