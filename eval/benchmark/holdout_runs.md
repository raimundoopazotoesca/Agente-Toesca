# Holdout Set — registro de corridas

Toda corrida que cargue casos `split: holdout` (desde el repo privado
`toesca-benchmark-holdout-private`) debe registrarse aquí **antes** de
ejecutarse. Ver política de contaminación en `cases/holdout/README.md`.

No hay corridas registradas todavía — el Holdout Set v1 sigue en
construcción (Batch 1 de 5 completado, ver `HOLDOUT_SET_V1_DESIGN.md`).
Ninguna corrida es válida hasta el freeze de contenido
(`HOLDOUT_FREEZE_MANIFEST_SPEC.md`) exista para el `holdout_id` que se
va a evaluar. Cada corrida además produce su propio Evaluation Run
Manifest (`EVALUATION_RUN_MANIFEST_SPEC.md`) — el freeze de contenido y
la identidad de la corrida son documentos separados a propósito (el
freeze no depende de modelo/juez/params/fecha).

## [2026-08-24] Canonical Account Concept Surface v1 — medición final

- holdout_id (Holdout Freeze Manifest referenciado): `toesca-analyst-benchmark-v1-holdout-2026-08-13`
- run_id (Evaluation Run Manifest de esta corrida): `canonical-account-concept-surface-v1-2026-08-24`
- Commit SHA evaluado (automation_agent): `a70e5e38c3b3b9791b839bbdbca5af0e8e9473da` + working tree de este stage
- Modelo evaluado: `TrackAStructured` (deterministic-only; sin juez LLM)
- Propósito: medición final
- ¿Alguno de estos resultados se usó para tuning de prompts/semantic layer/synonyms/entity resolver/rubric/arquitectura? NO
- Ejecutado por: Codex

## [2026-08-24] Human Analytical Presentation v1 — holdout de presentación (interno, no repo privado)

- holdout_id: `eval/human_presentation_holdout_v1/holdout_v1.md` (holdout local del repo, no del `toesca-benchmark-holdout-private`; 13 casos de presentación, no de exactitud analítica)
- run_id: `human-presentation-v1-2026-08-24`
- Commit SHA evaluado (automation_agent): working tree sobre HEAD `8089e9c` (ver commit de esta stage en el reporte final)
- Modelo evaluado: `gpt-5.6-terra` vía servidor real (`scripts/ingesta_server.py`, puerto 8765), llamadas HTTP reales
- Propósito: medición final de la capa de presentación (no de AccountQuery/entity resolution/formulas)
- ¿Alguno de estos resultados se usó para tuning de prompts/semantic layer/synonyms/entity resolver/rubric/arquitectura? NO — se usaron sólo para corregir defectos deterministas de renderizado (ver "Bugs found and fixed" en el holdout), nunca para ajustar wording/tono más allá de esas correcciones.
- Ejecutado por: Claude (esta sesión), en working tree local.

## Plantilla de entrada

```
## [YYYY-MM-DD] <propósito breve>

- holdout_id (Holdout Freeze Manifest referenciado): ...
- run_id (Evaluation Run Manifest de esta corrida): ...
- Commit SHA evaluado (automation_agent): ...
- Modelo(s) evaluado(s) + versión resuelta: ...
- Modelo juez + versión resuelta: ...
- Propósito: medición final | otro (especificar)
- ¿Alguno de estos resultados se usó para tuning de prompts/semantic
  layer/synonyms/entity resolver/rubric/arquitectura? SI / NO
  - Si SI: qué casos quedan contaminados y su plan de reemplazo en v2.
- Ejecutado por: ...
```
