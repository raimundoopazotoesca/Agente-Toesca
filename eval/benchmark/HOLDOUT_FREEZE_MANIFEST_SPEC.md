# Holdout Freeze Manifest — spec (plantilla, NO congelado)

Identifica el **contenido del Holdout Set** de forma inmutable: qué casos
existen, contra qué snapshot de datos y qué versión de schema se
escribieron. **No contiene nada sobre qué modelo se evaluó, qué modelo
actuó de juez, con qué parámetros de inferencia, ni en qué fecha corrió
una evaluación.** Esos campos son de la evaluación, no del contenido, y
viven en `EVALUATION_RUN_MANIFEST_SPEC.md` — ver esa nota más abajo para
por qué la separación es obligatoria.

Una vez completo (21/21 casos, `status: reviewed` en el manifest), este
documento se congela como `HOLDOUT_FREEZE_MANIFEST.yaml` (dato) +
`HOLDOUT_SET_V1_FREEZE.md` (narrativa, análogo a `DEV_SET_V1_FREEZE.md`).
Un freeze de contenido nuevo (casos agregados, corregidos o retirados)
produce un `holdout_id` nuevo — nunca se sobrescribe uno existente.

## Campos que fija el Holdout Freeze Manifest

1. **`holdout_id`** — identificador de esta versión exacta del contenido
   holdout (ej. `toesca-analyst-benchmark-v1-holdout-2026-MM-DD` o un hash
   corto). Es lo que cada Evaluation Run referencia.
2. **`benchmark_version`** — `v1` (hereda del Dev Set).
3. **`case_count`, `tae_count`, `tce_count`, `turn_count`** — composición
   exacta del set congelado.
4. **`case_ids`** — lista completa de IDs (no revela contenido; el
   contenido real vive en el repo privado).
5. **`snapshot_sha256` + `snapshot_source_commit`** — el mismo pin de
   `snapshot.lock` usado por Dev. El holdout no introduce un snapshot
   nuevo en v1.
6. **`case_schema_sha256`** — hash de `schema/case.schema.json` en el
   momento del freeze. Si el schema cambia después, ese es un evento de
   versión (v2), no un re-freeze silencioso de v1.
7. **`private_repo_commit_sha`** — el commit exacto del repo privado
   (`toesca-benchmark-holdout-private`) cuyo contenido fue validado y
   congelado. Es el ancla real de "qué preguntas y ground truth exacto
   está congelado" — este repo (`automation_agent`) nunca tiene ese
   contenido, así que el ancla vive en el otro repo por necesidad.
8. **`private_repo_content_sha256`** — hash calculado sobre la
   concatenación ordenada de los archivos de caso (`cases/holdout/**/*.yaml`
   del repo privado), como evidencia adicional de integridad más allá del
   commit SHA (detecta un commit "vacío" que no cambió contenido, o un
   working tree sucio en el repo privado al momento del freeze).
9. **`frozen_at`** — fecha en que el CONTENIDO quedó congelado (distinta
   de la fecha de cualquier evaluación posterior que lo use).
10. **`human_signoff`** — quién aprobó el freeze final (referencia a las
    reglas de human review de `HOLDOUT_SET_V1_DESIGN.md`).

## Por qué el freeze de contenido no puede depender del modelo/juez/params

El mismo Holdout Set congelado se corre contra múltiples modelos
candidatos y, con el tiempo, contra múltiples versiones del juez. Si el
identificador del holdout incluyera esos campos, cada corrida nueva
implicaría (incorrectamente) un holdout distinto, rompiendo la
comparabilidad entre corridas y la trazabilidad de qué casos siguen
"limpios" (no usados para tuning) a través del tiempo. El holdout es una
propiedad del *contenido*; el modelo/juez/params/fecha son propiedades de
cada *uso* de ese contenido — de ahí `EVALUATION_RUN_MANIFEST_SPEC.md`
como documento separado que referencia `holdout_id`.

## Estado actual

- **0 `holdout_id` congelados.** Batch 1 (6/21 casos) en `status: draft`
  en `HOLDOUT_MANIFEST.yaml` (repo principal) / `MANIFEST_FULL.yaml`
  (repo privado) — pendiente de completar los 21 casos y de human review
  final antes de generar el primer `HOLDOUT_FREEZE_MANIFEST.yaml` real.
- `compute_freeze_manifest.py` (`build_holdout_freeze_manifest()`)
  implementa el cálculo de (5)(6)(8) automáticamente; (1)(3)(4)(7)(9)(10)
  se completan al momento del freeze real, no antes.
