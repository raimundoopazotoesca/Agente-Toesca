# Toesca Analyst Benchmark — Holdout Set v1 freeze

El contenido del Holdout Set v1 queda congelado por los artefactos de este
commit. Los 21 casos viven exclusivamente en el repositorio privado; este
repositorio sólo conserva la identidad de contenido no semántica.

## Identidad

- **Holdout ID:** `toesca-analyst-benchmark-v1-holdout-2026-08-13`
- **Manifest:** `HOLDOUT_FREEZE_MANIFEST.yaml`
- **Snapshot:** SHA-256 `592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c`, fuente `c9b1dd543b275b8d1ac7c7569bc95b126b319e4c`
- **Schema de casos:** SHA-256 `ea82692c69a8fc09984302c29152e3a0450414adee43da763254f6b1aac0002b`
- **Repositorio privado:** commit `b8786c364e2f36f47f99234813e44b79d9a0347f`, content SHA-256 `31ee563ecb3e307e0cf841b58f67fe57681b4204978ec4b3f2f7129797fc4f1a`
- **Sign-off humano:** Raimundo Opazo, 2026-08-13.

## Composición

- 14 TAE
- 7 TCE
- 18 turnos TCE
- 21 casos y 58 referencias de ground truth

## Relación con Dev y futuras corridas

El freeze de contenido Dev v1 permanece en
`0d3919220897204f5e080e00b65afd5148c43f46`. La extensión opcional
`status` de `case.schema.json` usada para gobernar este holdout no reescribe
ni reemplaza el freeze de contenido Dev.

Toda evaluación futura debe crear un `EVALUATION_RUN_MANIFEST` separado que
referencie este `holdout_id`. Este freeze no identifica modelos, juez,
parámetros de inferencia ni fecha de evaluación.
