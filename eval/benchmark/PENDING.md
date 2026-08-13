# Toesca Analyst Benchmark — zonas pendientes

Estas áreas no tienen ground truth reproducible en el snapshot pinneado
(`snapshot.lock`, commit `c9b1dd5`). No se inventan casos con
`expected_value` para ellas; entran como Nivel 8 (insufficient
information) o quedan fuera de v1. Ver `docs/toesca-analyst-benchmark-v1-design.md` §1.5, §15.

- **Renta UF/m² desde rent roll** — sin fórmula validada (ya anotado en
  `tests/eval/questions.yaml`).
- **Capex por activo** — sin fuente normalizada en el schema.
- **Morosidad** — no existe tabla. Cualquier pregunta de morosidad es un
  caso de Nivel 8, nunca de metric-replacement.
- **Serie histórica de arrendatarios/vencimientos** — `raw_rent_roll_line`
  en el snapshot pinneado solo tiene 2 períodos (2026-05, 2026-06). Sin
  evolución histórica posible.
- **`dscr`** — está en `derived_kpi` pero no validado contra CDG (ver
  memoria `project_leverage_block_estado`). Solo casos cualitativos, nunca
  `expected_value`.
- **Ocupación por residencia INMOSA (`raw_ocupacion_residencia_line`)** —
  existe en la DB de trabajo actual pero **no en el commit pinneado**
  (`c9b1dd5`) que define el snapshot v1: el archivo `memory/agente_toesca_v2.db`
  tiene cambios locales sin commitear que agregan esa tabla. Casos sobre
  ocupación INMOSA por residencia quedan fuera de v1; usar el agregado
  `INMOSA` en `raw_vacancia_manual` en su lugar, o esperar a v2 con un
  snapshot re-pinneado sobre un commit que la incluya.
- **Excel** — no existe capability de exportación en el camino del
  analista. Los 2 casos L7 que lo piden se marcan `capability: xlsx_export`
  y quedan `unscored` hasta que exista.
