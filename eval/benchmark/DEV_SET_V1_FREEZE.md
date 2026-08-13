# Toesca Analyst Benchmark — Dev Set v1 freeze

Estado congelado tras la auditoría global (sin blockers) y el fix de
unidad DSCR. A partir de este commit, el Dev Set v1 no recibe casos
nuevos ni modificaciones de contenido; solo holdout (aparte) y, si
corresponde, correcciones documentadas como nuevas versiones.

## Identidad de la versión

- **Commit SHA (freeze):** `bc71a44` (fix DSCR unit) — el commit que agrega este documento es el freeze commit; ver hash exacto en `git log -1` / mensaje de commit de este archivo.
- **Snapshot pinneado:** `snapshot.lock`, sha256 `592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c`, extraído del commit fuente `c9b1dd543b275b8d1ac7c7569bc95b126b319e4c` (`memory/agente_toesca_v2.db`)
- **BENCHMARK_TODAY:** `2026-08-13`
- **BENCHMARK_VERSION:** `v1`
- **Rubric:** v1.3
- **Judge:** Impl 1.2.0, judge model configurable (`gemini-flash-latest` = preferred provisional, no definitivo)

## Composición del Dev Set

- **34 TAE** (single-turn, scored) — levels L1–L6, L8 (L7/xlsx_export sin materializar, capability inexistente)
- **17 TCE** (multi-turn) — 45 turnos
- **51 casos totales, 79 turnos evaluables**
- **Split:** 51/51 `dev`, 0 `holdout`

## Fix aplicado antes del freeze

`fix(eval): use ratio unit for DSCR ground truth` — agrega `ratio` al
enum de `unit` en `schema/case.schema.json` y remapea los 3
ground-truth refs de DSCR (`tae-l8-002`, `tce-decisionchallenge-001` x2)
de `count` a `ratio`. Sin cambios a valores, tolerancias, preguntas,
expected_behavior ni ningún otro caso.

## Accepted gaps (no bloquean el freeze)

Heredados de `PENDING.md` (zonas sin ground truth reproducible en el
snapshot pinneado):
- Renta UF/m² desde rent roll — sin fórmula validada.
- Capex por activo — sin fuente normalizada en el schema (confirmado en
  batch 2: `dim_cuenta_eeff` no tiene cuenta de capex/mejoras/mantenimiento).
- Morosidad — no existe tabla.
- Serie histórica de arrendatarios/vencimientos — `raw_rent_roll_line`
  solo cubre 2026-05/06 en el snapshot pinneado.
- `dscr` — existe en `derived_kpi` pero no validado contra CDG. Nunca
  usado como `expected_value` definitivo en ningún caso del Dev Set;
  siempre tratado como "dato existente, confiabilidad no confirmada".
- Ocupación por residencia INMOSA — fuera del commit pinneado v1.
- Excel/xlsx_export — capability inexistente; L7 queda vacío, no forzado.

Identificados en la auditoría del Dev Set (2026-08-13):
- **Concentración temporal en 2026-06** — el período aparece en 29/51
  casos (57%) como uno de los períodos consultados. Es el ancla natural
  de "estado actual" (período más reciente con datos completos en el
  snapshot para la mayoría de las tablas/KPIs), no un error de diseño.
  Clasificado **ACCEPTABLE_GAP**. Consideración explícita para el
  diseño de holdout: variar deliberadamente el eje temporal (usar más
  períodos 2024–2025, evitar que "el mes más reciente" sea el default
  implícito en la mayoría de los casos de holdout).
- **Concentración de KPI** — `ltv` en 14/51 casos, `noi_mensual` en
  12/51. Son los KPIs con cobertura más limpia en el snapshot (los 3
  fondos, la mayoría de los períodos); se reutilizan como dato de fondo
  para habilidades distintas en cada caso (nunca se repite la habilidad
  principal). Clasificado **ACCEPTABLE_GAP**.
- **Concentración de entidad** — Mall Curicó (5 casos) y Apo3001 (4
  casos) son las entidades más reutilizadas, ambas por tener señales
  reales verificadas (discrepancia de fuentes, vacancia persistente)
  aprovechadas en comportamientos distintos. <10% de los 51 casos cada
  una. Clasificado **ACCEPTABLE_GAP**.
- **Unidad `count` en KPIs de razón** — corregido en este freeze (ver
  fix arriba).
- **Holdout** — 0 casos, diseño pendiente, deliberadamente fuera de
  alcance de este freeze.

## Validación al momento del freeze

- Schema + cross-field validation: OK (`cases_loader.load_cases`)
- `python -m pytest eval/benchmark/tests -q`: 125/125 passed
- 127 ground_truth_refs materializados contra el snapshot pinneado: 0 errores, 0 NULL
- IDs únicos: 51/51
- Ninguna fecha observada posterior a BENCHMARK_TODAY (única fecha futura en el set es `fecha_vencimiento` contractual de un crédito, 2028-01-01 — dato legítimo, no observado)
- 0 menciones de Track A/Track B/Judge/modelos específicos dentro de `cases/`
