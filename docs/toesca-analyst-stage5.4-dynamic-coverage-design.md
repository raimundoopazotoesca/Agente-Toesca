# Stage 5.4 — Dynamic Coverage: diseño (no implementado)

## 1. Arquitectura actual relevante

Flujo: `OpenAIResponsesAnalystSession.ask` → `AnalystLoop.investigate()` (tools/analyst_runtime/analyst_loop.py) → acciones (`tools/analyst_runtime/actions.py`) → `ToolEvidence`/`ToolResult` (transport.py:45-73) → `session.py` recolecta evidencia y decide finalización → `canonical_guard.validate_and_render` cuando hay claims canónicos → `B.3 OpenAIResponsesFinalPresenter` (presentation.py) → usuario.

No existe una clase `RunEvidence`; la unidad real es `ToolEvidence` (transport.py:45-54), con campo `coverage: dict | None` ya declarado pero **nunca poblado** en ningún sitio del código.

Solo `_AnalyticsCapabilityAction` (actions.py:316-339) produce `ToolEvidence(evidence_class="canonical_metric")`, y solo si `result_kind == "scalar" and len(rows) == 1`. `RunSqlAction` (actions.py:132-149) nunca produce evidencia — su output vive solo en el content JSON visible al modelo (`row_count`, `columns`, `rows`, `truncated`, actions.py:76-84) y en el trace (actions.py:261-267), sin llegar a `ToolEvidence`.

`session.py:195-197` filtra `canonical = [e for e in evidence if e.evidence_class == "canonical_metric" and len(e.facts) == 1]` — es el único discriminador estructural hoy entre evidencia canónica y todo lo demás.

## 2. Coverage signals ya disponibles

- `ToolEvidence.scope` (fund/asset dict) — ya presente en evidencia canónica.
- `ToolEvidence.coverage` — campo existe, vacío. Punto de extensión natural, no requiere nuevo tipo.
- `row_count` de SQL — solo en content/trace, no en evidencia.
- `entity_id`, `period`, `metric_key` por fact (actions.py:335-336), alineado con `canonical_metric_claims` del envelope (synthesis_schema.py:8).
- `MetricDefinition.entity_grain` ("fund"|"asset") y `DatasetDefinition.grain` — declaran granularidad, no universo concreto (no listan qué activos pertenecen a qué fondo en qué período).
- `EntityResolver` conoce `active` (booleano derivado de `vigente_hasta`) por candidato, pero no se usa para nada excepto exponerse al modelo (resolver.py:37).
- `dim_activo.vigente_hasta` en DB (migración 050) — alcanzable solo indirectamente vía resolver, no vía runtime.

## 3. Huecos reales

- No hay universo esperado por fondo/período en ningún catálogo — no existe query "activos aplicables a TRI en 2026-06".
- `ToolEvidence.coverage` no se calcula.
- SQL (run_sql) no produce evidencia estructurada en absoluto: no puede participar en ninguna validación de coverage sin cambio.
- `active`/`vigente_hasta` no filtra ni gatea nada — solo es informativo.
- `B.3 FinalPresenter` solo ve `(user_message, draft_answer)` como strings — no tiene acceso a evidencia ni coverage (presentation.py:37-63). No puede, hoy, saber si la respuesta pretende exhaustividad.
- `SynthesisEnvelope` no tiene ningún fragment type que declare intención de exhaustividad ("esto es una lista completa" vs "esto es una muestra").

## 4. Sufficiency (definición operativa v1)

- **Scalar canonical lookup**: 1 `ToolEvidence(evidence_class="canonical_metric")` con 1 fact que resuelve el claim → suficiente. Ya cubierto por Stage 5.3, sin cambios.
- **Individual asset analysis**: evidencia sobre esa entidad sola es suficiente; no requiere evidencia de otras entidades del mismo fondo salvo que la respuesta compare o rankee.
- **Ranking/enumeration sobre un universo** (fondo completo o subset explícito): suficiente **si y solo si** el conjunto de entidades cubiertas en la evidencia == universo esperado (fondo completo, derivado del catálogo/relación entidad-fondo con filtro de vigencia) o == subset pedido explícitamente por el usuario.
- **Raw SQL**: nunca es suficiente por sí solo para un claim de exhaustividad — puede aportar filas de soporte pero no autoridad de coverage (row_count no prueba completitud semántica).

## 5. Exhaustiveness (definición operativa v1)

Una respuesta "pretende exhaustividad" cuando el tipo de acción/tool ejecutado tiene semántica de:
1. **universe enumeration** (p.ej. "listar todos los activos de un fondo").
2. **ranking/comparison sobre universo** (ordenar N entidades de un conjunto declarado).
3. **aggregate/breakdown** cuyo grain implica "todas las filas del universo aplicable" (p.ej. vacancia consolidada por fondo desglosada por activo).

Fuera de eso (lookup puntual, análisis de una entidad, "dame algunos ejemplos"), no se exige coverage completa.

## 6. Universo esperado y cómo derivarlo

Derivar dinámicamente de relaciones ya existentes, sin nuevo catálogo:
- Relación fondo→activo: ya modelada en DB (`dim_activo.fondo_key` / jerarquía activo↔sociedad↔fondo, ver memoria `project_tri_consolidacion_arquitectura`) y parcialmente expuesta vía `EntityResolver`/`parent_context_fields` (entities/catalog.py).
- Filtrar por vigencia: `vigente_hasta` (o equivalente) respecto al período consultado — ya existe la columna, falta que el runtime la consulte para construir el universo esperado (hoy solo se usa para un booleano informativo).
- Si el usuario pide un subset explícito ("rankea estos tres activos"), el universo esperado = el subset nombrado, no el fondo completo — se deriva de las entidades que el usuario mencionó/resolvió en la conversación, no de una regla nueva.

Necesita una función pequeña tipo `expected_universe(scope, period) -> set[entity_id]` que consulte la relación fondo→activo con filtro de vigencia — usa datos existentes, no requiere catálogo nuevo ni reglas hardcodeadas por métrica.

## 7. Temporal applicability

Ya modelada parcialmente (`vigente_hasta` en `dim_activo`, migración 050). Hueco: el runtime no la consulta al construir universo. Para v1 basta con que `expected_universe()` excluya activos con `vigente_hasta < período_consultado`. No requiere modelo temporal nuevo. Si `vigente_hasta` es NULL/desconocido, tratar como vigente (fail-open en applicability, fail-closed solo en coverage-completeness si el gap es material — a decidir en implementación, no en diseño).

## 8. Relación ToolEvidence / RunEvidence

No hay `RunEvidence` — es `ToolEvidence` per-tool-call, agregado por `session.py`. Propuesta: **poblar el campo `coverage` ya existente en `ToolEvidence`** (no crear nueva clase) con:
```
{scope_kind, scope_id, period, universe_kind, eligible_count, observed_count, complete}
```
Poblado solo por `_AnalyticsCapabilityAction` (y opcionalmente una nueva variante para SQL, ver §9). `session.py` agrega estos objetos al momento de decidir finalización, igual que hoy agrega `canonical`.

## 9. Tratamiento de raw_sql

`RunSqlAction` sigue sin generar `evidence_class="canonical_metric"`. Para que row_count de SQL pueda alimentar coverage sin darle autoridad indebida: adjuntar `ToolEvidence(evidence_class="raw_exploration", coverage={..., complete: unknown_or_false})` — explícitamente marcado como no autoritativo. La validación de coverage debe tratar `raw_exploration` como evidencia de soporte, nunca suficiente por sí sola para satisfacer un claim de exhaustividad. Esto es un cambio mínimo a `actions.py` (dar a SQL una evidencia, no cambiar su semántica).

## 10. Cómo detectar que una respuesta requiere exhaustividad — 3 opciones evaluadas

**A. Tool/capability semantics declaran exhaustividad** — cada capability de analytics (o el propio `RunSqlAction` cuando el query semánticamente es un listado) declara en su definición si su resultado, por diseño, representa "todas las filas del universo aplicable" (p.ej. `result_kind == "list"` sobre grain=fund con breakdown=asset). Determinístico, sin NLP, se deriva de metadata ya existente (`result_kind`, `entity_grain`, breakdown dims).

**B. Structured finalization declara un tipo de coverage requirement** — el modelo, al construir el `SynthesisEnvelope`, marca explícitamente cada claim/fragment con `requires_full_coverage: bool`. Requiere confiar en que el LLM declare correctamente su propia intención — no es puramente determinístico, y el diseño pide explícitamente no delegar esto al LLM como único juez (§3 del brief).

**C. La Session conoce el requested universe por el workflow ejecutado** — igual que A pero a nivel de sesión/loop en vez de por-tool: `AnalystLoop` observa qué acciones se ejecutaron (p.ej. `resolve_entity` con múltiples candidatos + capability con breakdown por activo) e infiere el universo solicitado combinando trazas. Más flexible pero más complejo — requiere heurística sobre secuencias de tool calls, no un solo punto de verdad.

**Recomendación: A.** Es la más pequeña, determinística y ya deriva de metadata existente (`result_kind`, `entity_grain`, presencia de dimensión de breakdown = activo). No requiere que el LLM se autoevalúe (evita B) ni heurísticas sobre secuencias (evita C). Se implementa marcando en la capability/tool definition, no en el output del modelo.

## 11. Contrato mínimo propuesto

- `ToolEvidence.coverage: {scope_kind, scope_id, period, universe_kind, eligible_count, observed_count, complete}` — usa el campo ya existente.
- `_AnalyticsCapabilityAction` (y variante para SQL con `evidence_class="raw_exploration"`) calcula `coverage` cuando su capability tiene `result_kind` que implica universo (lista/breakdown), usando `expected_universe()` (§6).
- Punto de validación nuevo en `canonical_guard.py` (o módulo hermano `coverage_guard.py`): dado el conjunto de `ToolEvidence` con `coverage` presente y los `canonical_metric_claims`/fragments del envelope que impliquen universo completo, verificar `observed_count == eligible_count` (o cobertura del subset pedido). Si no, fail-closed → mensaje de limitación explícito, no bloqueo genérico.

## 12. ¿Requiere cambios a SynthesisEnvelope?

Mínimos, evitando nuevo fragment type: **no** agregar `coverage_claim`/`exhaustive_claim` como tipo nuevo de fragment. En su lugar, la validación de coverage ocurre en el mismo punto que canonical_guard, comparando evidencia de la ronda contra qué tipo de capability/tool se invocó (regla A de §10) — no necesita que el modelo declare nada nuevo en el envelope. Si en implementación se demuestra que hace falta saber "el modelo pretendía enumerar todo" de forma explícita, evaluarlo ahí con evidencia concreta de que A no basta — no agregarlo preventivamente.

## 13. Flujo PASS

Usuario pide ranking de activos de TRI → capability con `entity_grain=asset`, breakdown por activo, `result_kind="list"` → acción calcula `eligible_count` = `len(expected_universe(fund=TRI, period))`, `observed_count` = filas devueltas → si iguales, `coverage.complete=True` → canonical_guard/coverage_guard no bloquea → B.3 presenta normalmente.

## 14. Flujo coverage gap

Mismo caso pero el tool devolvió solo 3 de 5 activos aplicables (p.ej. filtro implícito, error de tool) → `coverage.complete=False`, `eligible_count=5, observed_count=3` → validación falla-cerrado antes de finalización → el loop debe forzar una respuesta que declare la limitación (no bloquear con error genérico) — análogo a como `clarification_required` hoy corta el flujo, pero el texto debe ser "cobertura parcial: N de M activos", no "no puedo responder".

## 15. B.3 boundary

`B.3 FinalPresenter` no debe convertir una respuesta con `coverage.complete=False` en una afirmación de totalidad. Como B.3 no ve evidencia (solo strings), la salvaguarda debe ocurrir **antes** de B.3: el texto que entra a `draft_answer` ya debe reflejar la limitación (igual que hoy ocurre con `_clarification_text` para `clarification_required`, analyst_loop.py:136-201). No se propone dar a B.3 acceso a evidencia — mantiene su contrato actual intacto, evita rediseño de presentación.

## 16. Traces propuestos

`coverage_validation_applied`, `coverage_scope`, `coverage_universe_kind`, `coverage_expected_count`, `coverage_observed_count`, `coverage_complete`, `coverage_gap_count`, `coverage_validation_result` — todos derivables directamente del objeto `coverage` ya calculado, sin razonamiento oculto adicional.

## 17. Goldens (ver casos A–J del brief)

Mapeo directo a §5/§10: A (scalar) y F (individual asset) → PASS sin validación de coverage (fuera de alcance de la regla A). B/D → PASS con `complete=True`. C/E → coverage guard dispara, respuesta debe declarar parcialidad, no presentarse como completa. G → SQL con `evidence_class=raw_exploration` nunca satisface el requisito por sí solo. H → `expected_universe()` excluye entidades fuera de vigencia (p.ej. Machalí post `vigente_hasta`). I → universo = subset explícito nombrado por el usuario, derivado de las entidades resueltas en la conversación, no del fondo completo. J → `clarification_required` sigue cortando antes de llegar a esta validación (session.py:199-200 ya bypassa finalización estructurada).

## 18. Tests

Unit: `expected_universe()` con/sin filtro de vigencia, con subset explícito. Unit: `_AnalyticsCapabilityAction`/nueva variante SQL poblando `coverage` correctamente para result_kind con y sin breakdown. Unit: nuevo `coverage_guard` — PASS cuando complete, fail-closed cuando no, ignorado cuando el tool no implica universo. Integration: casos A–J como goldens contra `tests/analyst_runtime/`, `tests/test_analyst_conversation_integration.py`.

## 19. Archivos que probablemente cambiarían

`tools/analyst_runtime/actions.py` (poblar `coverage`, dar evidencia a SQL), `tools/analyst_runtime/transport.py` (posible tipado más fuerte de `coverage`, no estructura nueva), nuevo `tools/analyst_runtime/coverage_guard.py` (o extensión de `canonical_guard.py`), `tools/analyst_runtime/analyst_loop.py` (enganchar validación + texto de gap, análogo a `_clarification_text`), `tools/analyst_runtime/session.py` (invocar validación tras recolectar evidencia, antes de finalización estructurada), posible función nueva `expected_universe()` en `tools/entities/` o `tools/analytics/` (reutilizando catálogos existentes), tests correspondientes.

## 20. Riesgos

- `expected_universe()` mal derivado (jerarquía fondo→activo tiene casos ambiguos ya documentados, ver memoria `project_estructura_fondos` y las 4 entidades Apoquindo) — riesgo de falsos negativos/positivos si no se reutiliza exactamente la lógica de consolidación ya validada.
- Confundir "el tool no soporta breakdown completo" con "coverage incompleta real" si `result_kind`/`entity_grain` no están anotados con precisión suficiente en el Metric Catalog hoy.
- Mensaje de gap mal calibrado podría sobre-bloquear preguntas legítimas de tipo "análisis de un activo" si la regla A se aplica de forma demasiado amplia.

## 21. Qué queda explícitamente fuera de v1

Causalidad, calidad subjetiva de análisis, "análisis completo" en sentido amplio, lenguaje cualitativo abierto, document/vector coverage, mercado externo, Inciti, file coverage, semantic completeness general, cambios a B.3, nuevo fragment type en el envelope (salvo necesidad demostrada en implementación), modelo temporal nuevo más allá de `vigente_hasta` existente.

## 22. Provider calls

0 en esta fase de diseño. No Terra, no Sol.

## 23. DB status

Solo lectura durante diseño. Sin migraciones. DB source: SHA `D3C465FD92BA0C3F842F8F4CA8FDFEF7728E822FB75639F9B4CF71E28891BECF`, `schema_version=83`, `integrity_check=ok` — sin cambios.

## 24. Recomendación GO / NO-GO

**GO**, con scope acotado a: (1) poblar `ToolEvidence.coverage` (campo ya existente) desde capabilities con semántica de universo (regla A), (2) dar evidencia `raw_exploration` no autoritativa a `run_sql`, (3) `expected_universe()` reutilizando la jerarquía fondo→activo y `vigente_hasta` ya existentes, (4) un guard nuevo y pequeño (`coverage_guard.py`) que se ejecuta antes de finalización estructurada, análogo en forma a `canonical_guard.py`, (5) sin cambios a `SynthesisEnvelope` ni a B.3. Riesgo principal es la corrección de `expected_universe()` sobre la jerarquía Apoquindo ya conocida como ambigua — mitigar reutilizando exactamente la lógica de consolidación validada en Stage anterior, no reimplementarla.
