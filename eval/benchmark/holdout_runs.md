# Holdout Set — registro de corridas

Toda corrida que cargue casos `split: holdout` (desde el repo privado
`toesca-benchmark-holdout-private`) debe registrarse aquí **antes** de
ejecutarse. Ver política de contaminación en `cases/holdout/README.md`.

No hay corridas registradas todavía — el Holdout Set v1 sigue en
construcción (Batch 1 de 5 completado, ver `HOLDOUT_SET_V1_DESIGN.md`).
Ninguna corrida es válida hasta el freeze final (`HOLDOUT_SET_V1_FREEZE_SPEC.md`).

## Plantilla de entrada

```
## [YYYY-MM-DD] <propósito breve>

- Commit SHA evaluado (automation_agent): ...
- Commit/tag del repo privado holdout: ...
- Casos incluidos: [lista de IDs, o "todos"]
- Modelo(s) evaluado(s) + versión: ...
- Propósito: medición final | otro (especificar)
- ¿Alguno de estos resultados se usó para tuning de prompts/semantic
  layer/synonyms/entity resolver/rubric/arquitectura? SI / NO
  - Si SI: qué casos quedan contaminados y su plan de reemplazo en v2.
- Ejecutado por: ...
```
