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
