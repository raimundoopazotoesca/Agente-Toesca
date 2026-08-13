# Evaluation Run Manifest — spec (plantilla)

Identifica **una corrida de evaluación concreta**: qué código se evaluó,
con qué modelo, juzgado por qué juez, con qué parámetros, cuándo. Cada
Evaluation Run **referencia** un `holdout_id` congelado
(`HOLDOUT_FREEZE_MANIFEST_SPEC.md`) — nunca redefine ni recalcula la
identidad del contenido holdout.

Esta separación existe porque `DEV_SET_V1_FREEZE.md` mezclaba identidad de
contenido con identidad de ejecución en un solo documento; para el
Holdout Set eso se vuelve un problema real apenas hay más de una corrida
(comparar dos modelos, o la misma arquitectura en dos fechas) — sin
separarlos no se puede distinguir "cambió el agente" de "cambió el juez"
entre dos resultados.

## Campos que fija el Evaluation Run Manifest

1. **`holdout_id`** — referencia obligatoria al Holdout Freeze Manifest
   evaluado. Una corrida sin `holdout_id` resuelto a un freeze real no es
   una corrida holdout válida (ver `holdout_runs.md`).
2. **`run_id`** — identificador de esta corrida (timestamp o hash corto).
3. **`code_commit_sha`** — commit de `automation_agent` del sistema BAJO
   PRUEBA (agente Track A/B), no del benchmark.
4. **`evaluated_model`** — proveedor + nombre exacto + versión/fecha de
   snapshot del modelo evaluado (ej. `claude-sonnet-5-20260201`, nunca
   solo "sonnet" ni un alias sin resolver).
5. **`judge_model_resolved`** — mismo nivel de detalle para el juez.
   `gemini-flash-latest` no es válido aquí sin resolver: se registra el
   ID de modelo concreto al que resolvió en el momento de la corrida.
6. **`judge_py_sha256`, `rubric_yaml_sha256`, `runner_config_sha256`,
   `adapter_sha256` (por adapter usado)** — identifican la implementación
   del motor de scoring en el momento de la corrida. A diferencia del
   `case_schema_sha256` (que es del contenido, va en el Freeze Manifest),
   estos SÍ pueden cambiar entre corridas del mismo holdout congelado
   (nueva versión de rúbrica, fix del juez) y por eso viven aquí.
7. **`inference_params_evaluated`, `inference_params_judge`** —
   temperature, max_tokens, seed, top_p, cualquier parámetro no-default
   de ambos modelos.
8. **`eval_date`** — fecha real en que corrió la evaluación (distinta de
   `frozen_at` del holdout y de `BENCHMARK_TODAY`).
9. **`purpose`** — `measurement` (medición final válida) o una etiqueta
   explícita de por qué NO es medición final (ej. `debug`,
   `infra-smoke-test`). Ninguna corrida con propósito distinto de
   `measurement` cuenta para reportar resultados del modelo.
10. **`tuning_contamination_flag`** — boolean + notas: ¿algún resultado de
    esta corrida se usó para ajustar prompts/semantic layer/synonyms/
    entity resolver/rubric/arquitectura? Si `true`, los casos de esa
    corrida quedan contaminados (ver política en
    `cases/holdout/README.md`) y deben registrarse como tal en
    `holdout_runs.md` con su plan de reemplazo en v2.

## Relación con `holdout_runs.md`

`holdout_runs.md` es el registro humano-legible (bitácora) de corridas
autorizadas. Un Evaluation Run Manifest es el artefacto de datos
estructurado (JSON, vía `compute_freeze_manifest.py:
build_evaluation_run_manifest()`) que respalda cada entrada de esa
bitácora. Ninguna corrida holdout es válida sin ambos: la entrada en la
bitácora (autorización + propósito declarado de antemano) y el manifest
de la corrida (identidad técnica exacta, generado en el momento).

## Estado actual

No hay corridas registradas. Ningún `holdout_id` existe todavía para
referenciar (ver `HOLDOUT_FREEZE_MANIFEST_SPEC.md` — Batch 1 de 5, sin
freeze de contenido). `compute_freeze_manifest.py` implementa
`build_evaluation_run_manifest(holdout_id=..., evaluated_model=...,
judge_model_resolved=..., eval_date=..., ...)` para cuando exista un
`holdout_id` real que referenciar.
