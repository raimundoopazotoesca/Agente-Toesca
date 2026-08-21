# Stage 5.4 — Dynamic Coverage: diseño v2 (cierra 3 huecos de v1, no implementado)

Este documento reemplaza las secciones 5.1 (Option A recomendada sola), 9 (raw_sql) y parte de 3/6/7/11/12 del [v1](toesca-analyst-stage5.4-dynamic-coverage-design.md). El resto de v1 (catálogos existentes, B.3 boundary general, traces, prohibiciones de scope) sigue vigente.

## 1. Exhaustiveness bypass — Option A sola no cierra el caso

Caso: usuario pide "todos los activos de TRI"; el modelo llama `run_sql` (o obtiene evidencia `governed_dataset` parcial) y luego escribe **texto libre** ("Los activos de TRI son: A, B, C...") sin pasar por ningún fragment ligado a evidencia.

Con Option A (capability semantics solamente), la evidencia sí queda marcada con `coverage.complete=False` o inexistente — pero **nada obliga a que el fragment `raw_text`/`text` del envelope pase por esa evidencia**. `raw_text` es contenido no gobernado por diseño (synthesis_schema.py:1-9): el modelo puede escribir cualquier lista de nombres ahí sin que ningún validador la toque. Coverage metadata correcta en `ToolEvidence` es necesaria pero no suficiente si el canal de salida que el modelo usa para enumerar entidades no está atado a esa evidencia. **Option A se rechaza como solución completa** — cierra el caso "gobernado pero parcial", no el caso "raw-only presentado como completo".

Option B (el modelo autodeclara `requires_full_coverage`/coverage claim en finalization) se rechaza igual que en v1: depende de que el LLM juzgue correctamente su propia intención de exhaustividad — es exactamente el "LLM como único juez" que el diseño original prohíbe (§3 del brief inicial), y no es determinístico ni auditable sin inspeccionar el draft.

**Option C — capability semantics + fragment tipado que renderiza enumeraciones/rankings desde evidencia — es la elegida**, con una extensión adicional necesaria para cerrar también el caso raw-only: reutilizar el mecanismo de integridad **ya existente** en B.3 (`_integrity_status`, presentation.py:66-79), que hoy compara el *set de números* del draft contra los números renderizados desde `canonical_metric_claims`, y ampliarlo para comparar también el **set de entidades nombradas** del draft contra las entidades efectivamente renderizadas desde `governed_dataset` fragments. Esto no es NLP ni regex de intención: es la misma comparación estructural de conjuntos (draft vs. render) que Stage 5.3 ya usa para números, aplicada a identificadores de entidad. Si el draft menciona entidades que no provienen de un fragment gobernado y coverage-validado, la integridad falla y cae al mismo fallback que ya existe (`_fallback`, presentation.py:90-91) — no se rediseña el contrato de B.3 (`present(user_message, draft_answer)` no cambia), solo se amplía qué compara `_integrity_status` internamente, tal como ya compara números.

Esto sí cierra el caso raw-only: si el modelo enumera activos en texto libre sin fragment, el set de entidades del draft no tiene contraparte renderizada → integridad falla → fallback (respuesta degradada/con limitación), igual que hoy pasa si el draft inventa un número no respaldado por `canonical_metric_claims`.

## 2. Governed non-scalar evidence — contrato mínimo

Nuevo `evidence_class="governed_dataset"`, producido por `_AnalyticsCapabilityAction` (o acción hermana) cuando `result_kind` implica multi-row (`"list"`, `"ranking"`, `"breakdown"` — es decir, cuando hoy la acción NO produce evidencia porque `len(rows) != 1`). Estructura, reusando `ToolEvidence` tal cual (transport.py:45-54), sin tocar el guard de Stage 5.3:

```
ToolEvidence(
  evidence_id=...,
  evidence_class="governed_dataset",
  source={...},                          # igual que hoy
  scope={"fund": ..., "asset": ...},     # igual que hoy
  semantic_contract={                    # metric/dataset identity + grain
      "metric_key"|"dataset_key": ...,
      "entity_grain": ...,               # de MetricDefinition/DatasetDefinition
      "period_grain": ...,
  },
  provenance={...},                      # igual que hoy (ingest_run_ids, etc.)
  coverage={                             # ver §3
      "universe_kind": ..., "eligible_count": ..., "observed_count": ...,
      "status": "complete"|"partial"|"unknown",
  },
  facts=tuple(                           # una entrada por fila observada
      {"entity_id":..., "period":..., "metric_key":..., "value":..., "unit":...}
      for row in rows
  ),
)
```

`facts` multi-elemento es intencional y está permitido porque **no entra al canonical scalar guard** (canonical_guard.py:15-48 sigue exigiendo `evidence_class == "canonical_metric"` y 1 fact — sin cambios). Un guard nuevo y separado (`coverage_guard.py`, §11 v1) valida `governed_dataset` contra su propio fragment type (§5).

## 3. Expected universe certainty — complete / partial / unknown

Corrige v1 §7, que trataba `vigente_hasta` NULL como "vigente por defecto" — **eso queda prohibido explícitamente por el usuario**. Regla revisada:

`coverage.status = "complete"` únicamente si las 4 condiciones se cumplen simultáneamente:
1. **Scope demostrado**: la entidad de scope (fondo/activo) proviene de `EntityResolver` con `resolution_status == "resolved"` (no ambiguous/low_confidence/not_found).
2. **Universo determinístico**: existe una función de pertenencia fondo→activo sin ambigüedad para ese scope+período (evita los casos ya conocidos como ambiguos, p.ej. las 4 entidades Apoquindo — si el scope resuelto cae en uno de esos casos sin mapeo canónico explícito, la pertenencia NO se considera determinística).
3. **Applicability temporal decidible**: cada miembro candidato del universo tiene `vigente_hasta` (o campo equivalente) **conocido** (no NULL) respecto al período consultado. Un miembro con temporal applicability desconocida **no se asume vigente ni se excluye** — su sola presencia con dato faltante degrada el resultado completo a `unknown`, no a `complete` ni a exclusión silenciosa.
4. **Observación total**: `observed_count == eligible_count` sobre el universo así definido.

`coverage.status = "partial"`: condiciones 1-3 se cumplen (universo bien definido y decidible) pero `observed_count < eligible_count`.

`coverage.status = "unknown"`: cualquier falla en 1, 2 o 3 (scope ambiguo, universo no derivable determinísticamente, o al menos un miembro con temporal applicability indeterminada). `unknown` es el default seguro — nunca se infiere `complete` por ausencia de señal contraria.

No se crea modelo temporal nuevo: se usa `vigente_hasta` tal cual existe hoy (migración 050), solo se corrige cómo se interpreta su ausencia.

## 4. Raw SQL — decisión revisada: NO agregar evidencia a run_sql en v1

v1 proponía `ToolEvidence(evidence_class="raw_exploration")` para `run_sql` "porque el campo existe". Reevaluado: se descarta. Razón: bajo las reglas de §3, `run_sql` nunca puede aportar `scope` demostrado ni universo determinístico por construcción (es SQL libre) — cualquier evidencia que se le adjunte terminaría siempre en `coverage.status="unknown"` de todas formas, así que instrumentar `run_sql` con una clase de evidencia formal no cambia ningún resultado de validación, solo agrega superficie. El `coverage_guard` (§1, §5) ya trata la **ausencia** de evidencia `governed_dataset` como `unknown` para cualquier claim que la requeriría — eso cubre el caso "solo hubo SQL" sin tocar `actions.py:132-149`. `row_count` de SQL sigue sin ninguna relación con completeness, en ningún punto del flujo. Se revisita solo si en implementación se demuestra necesidad real de trazabilidad (no ahora).

## 5. ¿Cambios a SynthesisEnvelope? Sí, mínimos — autorizado explícitamente por el usuario

Se agrega:
- Un fragment type nuevo: `{"type": "governed_dataset_ref", "claim_id": ...}` (paralelo estructural a `canonical_metric_ref`, synthesis_schema.py:5-7).
- Un array nuevo `governed_dataset_claims`: `{claim_id, evidence_id, dataset_key|metric_key, entity_ids: [...], period, universe_kind}` (paralelo a `canonical_metric_claims`, synthesis_schema.py:8) — el modelo declara qué evidencia usa y qué entidades presenta, pero **no declara si es exhaustivo**; eso lo calcula el guard desde `coverage.status` de la evidencia referenciada, nunca desde la declaración del modelo. Esto evita repetir el error de Option B: el claim es sobre "qué evidencia estoy usando", no sobre "esto es completo".

El guard (`coverage_guard.py`) valida: claim.entity_ids ⊆ evidence.facts entities, y expone `coverage.status` de esa evidencia para que la respuesta final (vía la extensión de `_integrity_status`, §1) refleje partial/unknown cuando corresponda — no bloquea la respuesta, la degrada con la limitación explícita (igual criterio que v1 §15: B.3 no puede convertir parcial en total, pero el bloqueo real ocurre antes de B.3).

## 6. Flujos

**Exhaustive PASS** — "todos los activos de TRI", capability `governed_dataset` con `result_kind="list"`, scope resuelto, universo determinístico, todos con `vigente_hasta` conocido, `observed_count==eligible_count` → `coverage.status="complete"` → fragment `governed_dataset_ref` renderiza directo → integridad de entidades OK → B.3 presenta sin caveat.

**Partial** — mismo caso pero tool devolvió 3 de 5 → `coverage.status="partial"` → coverage_guard fuerza que la finalización incluya la limitación ("3 de 5 activos aplicables observados") antes de B.3 → integridad de entidades pasa porque el draft ahora sí refleja el subset real, no una afirmación de totalidad.

**Unknown** — scope ambiguo (p.ej. cae en el caso Apoquindo sin mapeo canónico) o algún activo candidato con `vigente_hasta` NULL en el período → `coverage.status="unknown"` → coverage_guard fuerza lenguaje de incertidumbre explícita ("no puedo determinar si esta lista es completa") — no se presenta como completa ni se bloquea totalmente la respuesta (activo individual analysis o subset explícito siguen sin requerir esto, ver v1 §4-5).

**Raw-only exhaustive attempt** — modelo llama solo `run_sql`, escribe en `raw_text` una lista de activos como si fuera completa → no existe `governed_dataset_ref` ni evidencia con entidades → extensión de `_integrity_status` detecta entidades en el draft sin contraparte renderizada desde evidencia gobernada → falla integridad → fallback (mismo mecanismo que hoy usa presentation.py:90-91 para números no respaldados).

## 7. Goldens ajustados (reemplaza C, E, G, H de v1 §17)

- C (lista parcial presentada como todos) → ahora explícitamente cubierta por el flujo **Partial** + integridad de entidades, no solo por coverage metadata sin consumidor.
- E (ranking parcial) → mismo mecanismo, `governed_dataset_ref` con `coverage.status="partial"`.
- G (raw SQL con filas parciales) → explícitamente el flujo **raw-only** — sin evidencia gobernada, sin autoridad, integridad de entidades lo atrapa si el draft enumera resultados como si fueran el universo.
- H (temporal applicability) → ahora corregido: NULL/desconocido → `unknown`, no inclusión silenciosa ni exclusión silenciosa.
- Nuevo caso K: scope ambiguo (Apoquindo) intentando enumeración completa → `unknown`, no `complete` ni error genérico.

## 8. GO / NO-GO

**GO para pasar a fase de implementación**, con el diseño v2 reemplazando la recomendación de "Option A sola" de v1. Puntos que deben materializarse en el plan de implementación (no ahora): (a) `governed_dataset` evidence class + su guard separado del scalar guard, (b) reglas complete/partial/unknown de §3 tal cual, sin default a complete, (c) `run_sql` **sin** cambios, (d) extensión mínima de `_integrity_status` en presentation.py para set de entidades (mismo mecanismo, no rediseño de B.3), (e) nuevo fragment type + claim array en `synthesis_schema.py`, ambos ya justificados aquí. Riesgo principal sigue siendo la exactitud de la función de pertenencia fondo→activo sobre los casos ya conocidos como ambiguos (Apoquindo) — bajo las reglas de §3 esos casos caen a `unknown` por diseño en vez de arriesgar un `complete` incorrecto, lo cual es el comportamiento fail-closed pedido.
