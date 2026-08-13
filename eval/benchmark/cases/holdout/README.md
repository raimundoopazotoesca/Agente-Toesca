# Holdout Set — política de aislamiento físico

Este directorio existe para que el *loader* (`cases_loader.load_cases`) y el
validador de schema tengan un lugar canónico donde buscar casos
`split: holdout`, y para que `tests/test_holdout_not_leaked.py` tenga un
único sitio que vigilar. **No contiene, y nunca debe contener, los YAML
reales con preguntas, `required_facts`, `forbidden_claims` ni
`ground_truth_refs` del Holdout Set.**

Las subcarpetas `tae/` y `tce/` se mantienen vacías en este repo
(`.gitkeep` únicamente). Cualquier archivo `*.yaml` que aparezca aquí en
una revisión de código es una señal de fuga y debe bloquear el merge.

## Dónde vive el contenido real

Los 21 casos reales (14 TAE + 7 TCE) viven en un repositorio Git **separado
y privado**, fuera de este working tree:

```
C:\Users\raimundo.opazo\toesca-benchmark-holdout-private\
  cases\holdout\tae\*.yaml
  cases\holdout\tce\*.yaml
```

Ese repositorio:

- no es un submódulo ni un remoto de `automation_agent`;
- no está listado como directorio de trabajo adicional de ningún agente
  de desarrollo (Claude/Codex) en este proyecto;
- no se abre, monta ni clona durante sesiones normales de desarrollo,
  tuning de prompts/synonyms/entity-resolver, ni iteración de
  arquitectura Track A/B;
- solo se referencia explícitamente durante una corrida de evaluación
  final autorizada (ver abajo).

Esta separación física es la salvaguarda principal. El test lógico
(`test_holdout_not_leaked.py`) es una segunda capa, no un sustituto: por
sí solo no evita que un agente de desarrollo lea el contenido si ese
contenido estuviera disponible en el working tree.

## Cómo se monta durante una corrida autorizada

`cases_loader.load_cases(root=...)` ya acepta una raíz arbitraria — no
requirió cambios de código. Una corrida de evaluación holdout autorizada
apunta explícitamente a la raíz externa:

```python
from pathlib import Path
from eval.benchmark.cases_loader import load_cases

holdout_cases = load_cases(
    root=Path(r"C:\Users\raimundo.opazo\toesca-benchmark-holdout-private\cases"),
    split="holdout",
)
```

Requisitos para que una corrida cuente como "autorizada":

1. Está registrada en `eval/benchmark/holdout_runs.md` (fecha, propósito,
   quién la ejecuta, commit SHA evaluado) — ver plantilla en ese archivo.
2. El propósito declarado es **medición final**, nunca tuning. Si el
   resultado de una corrida holdout se usa para ajustar prompts, semantic
   layer, synonyms, entity resolver, rubric o arquitectura, todos los
   casos usados en esa corrida quedan **contaminados** y deben
   retirarse/reemplazarse en la siguiente versión del benchmark.
3. Nadie copia los YAML del repo privado hacia `automation_agent/` ni los
   pega en un prompt, few-shot, verified query o regla de synonyms.

## Política de contaminación (resumen operativo)

Los casos Holdout:
- nunca aparecen en prompts/few-shots del sistema evaluado;
- nunca se convierten en verified queries;
- nunca inspiran reglas específicas de synonyms/entity resolution;
- nunca se usan para corregir Track A/B;
- nunca se usan para ajustar Rubric/Judge;
- nunca se usan para seleccionar arquitectura mediante iteración repetida.

Un caso usado para cualquiera de los fines anteriores queda contaminado y
se marca como tal en `holdout_runs.md`; debe ser reemplazado antes de la
siguiente versión congelada del benchmark.
