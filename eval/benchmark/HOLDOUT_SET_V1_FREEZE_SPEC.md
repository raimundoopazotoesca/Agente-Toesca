# Holdout Set v1 — spec de freeze reproducible (plantilla, NO congelado)

`DEV_SET_V1_FREEZE.md` fija el snapshot de datos y algunos metadatos de
versión, pero no separa explícitamente "cambió el agente" de "cambió el
juez". Para el Holdout Set, cada corrida de evaluación final debe fijar
**todas** las piezas que pueden mover el resultado, no solo la DB. Este
documento es la plantilla; se rellena y se congela (`HOLDOUT_SET_V1_FREEZE.md`)
recién cuando los 21 casos estén escritos, revisados y aprobados —
no antes.

## Identidad a fijar en cada corrida autorizada

1. **Commit SHA del código evaluado** (`automation_agent`, el sistema bajo
   prueba — agente/Track A/B, no el benchmark) — `git rev-parse HEAD` del
   commit exacto que corrió.
2. **sha256 del snapshot DB** — ya versionado en `snapshot.lock`
   (`592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c`,
   commit fuente `c9b1dd543b275b8d1ac7c7569bc95b126b319e4c`). Se hereda del
   Dev Set freeze; el holdout usa el mismo snapshot pinneado — no un
   snapshot nuevo.
3. **Hash de `graders/judge.py`** — identifica la implementación del juez
   (independiente de qué modelo LLM lo ejecuta).
4. **Hash de `graders/rubric.yaml`** — identifica la rúbrica exacta.
5. **Hash de `schema/case.schema.json`** — identifica el contrato de forma
   de los casos.
6. **Hash de la configuración/prompts relevantes del runner y de cada
   adapter usado** (`runner.py`, `adapters/*.py` que participen en la
   corrida) — el prompt de sistema del agente evaluado y el prompt del
   juez son ambos superficie de contaminación potencial.
7. **Modelo evaluado** — proveedor, nombre exacto de modelo y versión/fecha
   de snapshot del modelo (ej. `claude-sonnet-5-20260201`, no solo
   "sonnet"), más cualquier flag de configuración de arquitectura
   (Track A vs Track B, semantic layer on/off, etc.).
8. **Modelo juez** — mismo nivel de detalle. `gemini-flash-latest` es
   "provisional preferred" en el Dev Set freeze — la corrida holdout debe
   registrar el nombre de modelo *resuelto* en el momento de la corrida
   (un alias `-latest` no es reproducible por sí mismo; se resuelve a un
   ID de modelo concreto y se registra ese ID).
9. **Parámetros de inferencia relevantes** — temperature, max_tokens, seed
   si aplica, top_p, cualquier parámetro no-default tanto del modelo
   evaluado como del juez.
10. **Fecha de evaluación** (no confundir con `BENCHMARK_TODAY`, que es la
    fecha de referencia congelada de los datos, `2026-08-13`, y no cambia
    entre corridas del mismo v1).

## Por qué separar (6)-(9) de (1)-(2)

Un cambio de score entre dos corridas puede deberse a:
- cambio real en el agente evaluado (commit distinto) → (1);
- cambio en cómo se materializa el ground truth → no debería pasar nunca
  dentro de v1, (2) es fijo;
- cambio en el juez (nueva versión de `judge.py`/`rubric.yaml`, o el mismo
  código pero el modelo `-latest` resolvió a un checkpoint distinto) →
  (3)(4)(8);
- cambio en el schema de casos → (5), no debería pasar en un split
  congelado;
- cambio de parámetros de inferencia sin cambiar el modelo → (9).

Sin fijar y registrar los 10 puntos, una regresión o mejora observada en
holdout es ambigua: no se puede saber si mejoró el agente o si el juez se
volvió más laxo. Ese es el problema concreto que este spec cierra.

## Mecánica de captura (infra, no ejecución)

`eval/benchmark/compute_freeze_manifest.py` (agregado en este commit)
calcula sha256 de los archivos de (3)(4)(5)(6) y arma un dict con los
campos de (1)(2)(7)(8)(9)(10) a partir de argumentos/entorno. No ejecuta
ninguna corrida de evaluación ni toca el holdout — es solo la utilidad
para producir el bloque de identidad de una corrida real, cuando exista.

## Estado actual

- Holdout Set: **0/21 casos frozen**. Batch 1 (6/21) en estado `draft` →
  pendiente de human review (ver `HOLDOUT_SET_V1_DESIGN.md` §Reglas de
  human review).
- Este spec queda como plantilla hasta que el Holdout Set complete su
  propio freeze de contenido (`HOLDOUT_SET_V1_FREEZE.md`, análogo a
  `DEV_SET_V1_FREEZE.md`, no creado todavía).
- Ninguna corrida de evaluación holdout está autorizada hasta ese freeze
  de contenido. Ver `holdout_runs.md`.
