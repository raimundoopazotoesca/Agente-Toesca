# TRI — Consolidación Ingresos, NOI y Vacancia

> Metodología validada exacto contra CDG mar/abr/may-2026 (ingresos, NOI) y
> contra planilla del usuario jun-2026 (vacancia). Ver [[db]] sección
> "Vacancia histórica" para el detalle de las vistas `v_vacancia_*`.

## Universo de activos de TRI

TRI consolida 9 posiciones (7 activos reales, dos de ellos vía subfondo):

| Activo (raw) | Fondo dueño directo | Participación efectiva en TRI | Vía |
|---|---|---|---|
| INMOSA | TRI | 0,43 | directa |
| Viña Centro | TRI | 1,00 | directa |
| Mall Curicó | TRI | 0,80 | directa |
| Apo3001 | TRI (sociedad Chañarcillo) | 0,685 (GLA) / **1,00 (ingresos, NOI y vacancia)** | directa, ver excepción abajo |
| Sucden | TRI | 1,00 | directa |
| Torre A | PT | 0,3333 | look-through vía PT |
| Boulevard | PT | 0,3333 | look-through vía PT |
| Apo4501 | Apo | 0,30 | look-through vía Apo |
| Apo4700 | Apo | 0,30 | look-through vía Apo |

Participaciones desde `v_activo_fondo_efectivo` (fondo_key='TRI'). Machalí
(vendido sept-2025) queda excluido vía `dim_activo.vigente_hasta`.

### Excepción Apo3001

`dim_activo.participacion_en_sociedad` = 0,685 para Apo3001 (sociedad
Chañarcillo). Pero:
- **Ingresos y NOI**: el ER ingestado de Apo3001 ya es la contabilidad propia
  de Chañarcillo (TRI es dueño del 100% de la sociedad) → usar
  participación = **1,0**, no 0,685. Confirmado por el usuario 2026-07-20
  (ver `scripts/consolidate_ingresos_tri.py` / `consolidate_noi_tri.py`,
  `_PARTICIPACION_OVERRIDE`).
- **Vacancia (numerador, m² vacantes)**: misma excepción, participación =
  **1,0**. Confirmado 2026-08-03 (ver más abajo, sección Vacancia).
- **Vacancia (denominador, m² GLA)**: **NO** lleva la excepción, se pondera
  al 0,685 normal de `v_activo_fondo_efectivo`. Esto es asimétrico a
  propósito — validado contra la planilla del usuario (ver detalle abajo).

## Ingresos y NOI consolidados

Fuente: `derived_kpi` (`entidad_tipo='fondo'`, `entidad_key='TRI'`,
`kpi IN ('ingresos_mes','ingresos_u12m','noi_mes','noi_u12m')`). Se
recalculan con:

```
python -m scripts.consolidate_ingresos_tri
python -m scripts.consolidate_noi_tri
python -m scripts.recompute_derived_kpis
```

Fórmula: `SUM(ingresos_mensual(activo) x participacion_efectiva(activo, TRI))`
vía `v_activo_fondo_efectivo`, con la excepción Apo3001=1,0. `ingresos_mensual`
por activo (100%, bruto) viene de `raw_er_activo_line WHERE
seccion='INGRESOS_OPERACION'`; NOI de `WHERE es_operacional=1`
(ingresos + gastos operacionales).

**No se excluye ningún ingreso** (traspaso, recupero, parking) — se usa el
bruto completo, confirmado por el usuario 2026-07-20 activo por activo.

### Bug corregido 2026-08-03: PT (Torre A/Boulevard)

Los datos de Torre A/Boulevard en `raw_er_activo_line` venían de un archivo
temporal de scratchpad de otra sesión, mal parseado (ej. "Ingresos Torre A"
de un mes tenía en realidad el "NOI Mensual" de otro mes). Afectaba
principalmente abr/may-2026 (~10% de error) y en menor medida ~45 periodos
históricos 2021-2024 (~1-2%).

**Fix**: backfill manual completo de Torre A/Boulevard desde
`RAW/NOI PT.xlsx` (parseado con `tools/db/ingest_er_pt.py:parse_planilla`),
superseding las 957 filas viejas e insertando 958 correctas
(`ingest_run_id=139`). El backfill fue **manual, fuera de**
`ingest_er_pt.py` — ese script tiene un guardrail de "historia congelada"
(no toca periodos < `RULES_EFFECTIVE_PERIOD` = 2026-07) que se dejó intacto
a propósito para que el servidor de ingesta normal siga sin recalcular
historia. Si hay que re-hacer un backfill de historia completa de PT en el
futuro, hay que repetir el mismo patrón manual (no modificar
`ingest_er_pt.py`).

Validado tras el fix: ingresos y NOI de TRI mar/abr/may-2026 calzan exacto
contra el CDG del usuario.

### Backfill histórico Viña Centro + Mall Curicó (2026-08-03)

La serie consolidada de TRI (`ingresos_mes`/`noi_mes`) exige dato de
**todos** los activos vigentes en cada período (`_ingresos_mes_tri` /
`_noi_mes_tri`, ver arriba) — antes de este backfill, Viña Centro y Mall
Curicó solo tenían `raw_er_activo_line` desde ago-2023 (fuente detallada:
"RAW/NOI VIÑA.xlsx" / "RAW/NOI Curico.xlsx"), lo que cortaba toda la serie
de TRI en ago-2023 aunque el resto de los activos tuviera historia desde
2018.

El usuario aportó una planilla auxiliar **"RAW/NOI VIÑA DB.xlsx"** con
categorías agregadas (no cuenta por cuenta) **en UF** (no CLP, a diferencia
de la fuente detallada), hoja `Hoja1` = Viña Centro ene-2018→jul-2023, hoja
`curico` = Mall Curicó ene-2020→jul-2023 (Curicó no era parte de TRI antes
de ene-2020 — celdas en blanco a propósito, no dato faltante).

- Ingestado con `tools/db/ingest_er_vina_historico.py` y
  `tools/db/ingest_er_curico_historico.py` (idempotencia por
  `source_file`+`source_sheet`, no por `activo_key`, para no pisar los datos
  ago-2023+ de los scripts de detalle).
- Mall Curicó no tiene `vigente_hasta` (`dim_activo` no tiene columna
  `vigente_desde`) → se agregó `_VIGENCIA_DESDE_OVERRIDE = {"Mall Curicó":
  "2020-01"}` en `consolidate_ingresos_tri.py`/`consolidate_noi_tri.py`,
  mismo patrón que `_PARTICIPACION_OVERRIDE`.

**Resultado intermedio**: con el backfill, la serie pasó de arrancar en
ago-2023 a ene-2020 — seguía cortada porque **Apo3001** (`raw_er_activo_line`
min periodo 2020-01) y **Apoquindo** (Apo4501/Apo4700, min periodo 2019-01)
también son vigentes desde el origen de TRI (sin `vigente_hasta`) y no
tenían dato antes de esas fechas.

**Resultado final**: el usuario confirmó 2026-08-03 que esas SÍ son las
fechas reales de incorporación a TRI (Apo3001 ene-2020, Apoquindo ene-2019
— no un hueco de datos) y que el criterio es que el gráfico consolidado
arranque igual en **ene-2018**, sin el aporte de los activos aún no
incorporados en cada período (no se perciben sus ingresos/NOI, no cuentan
para la vacancia). Se extendió `_VIGENCIA_DESDE_OVERRIDE` en
`consolidate_ingresos_tri.py`/`consolidate_noi_tri.py`:

```python
_VIGENCIA_DESDE_OVERRIDE = {
    "Mall Curicó": "2020-01",
    "Apo3001": "2020-01",
    "Apoquindo": "2019-01",
}
```

`ingresos_mes`/`noi_mes` de TRI ahora cubren **101 períodos, ene-2018 a
may-2026** (antes 34, ago-2023 a may-2026). La vacancia consolidada
(`_fetch_vacancia_tri` en `scripts/build_factsheet.py`) nunca tuvo esta
restricción — ya sumaba solo los activos con dato disponible por período,
sin exigir el universo completo.

## Vacancia consolidada

Fuente: vistas `v_vacancia_*` (ver [[db]]), **no** `derived_kpi` — no hay un
KPI cacheado de vacancia consolidada de TRI, se calcula al vuelo.

### Bug corregido 2026-08-03: case-sensitivity en detección de vacantes

`v_vacancia_activo_tipo` filtraba `arrendatario = 'Vacante'` (case-sensitive),
pero el rent roll trae tanto `'Vacante'` como `'vacante'` (minúscula).
Las unidades en minúscula (19 en Apo4501 = 961,96 m², 2 en Apo4700 = 2 m²)
quedaban contadas como GLA ocupada en vez de vacante. Fix en migración
`tools/db/migrations/077_fix_vacancia_case.sql`: `LOWER(arrendatario) =
'vacante'`. Recrea las 5 vistas de la cadena (`v_vacancia_activo_tipo`,
`v_vacancia_activo`, `v_vacancia_activo_efectivo`,
`v_vacancia_pt_consolidado_tipo`, `v_vacancia_apoquindo_consolidado_tipo`)
porque SQLite no permite `ALTER VIEW`.

### Filtro de tipo_unidad por activo (confirmado por el usuario 2026-08-03)

No todos los activos usan el mismo universo de `tipo_unidad`:

| Activo | Tipos incluidos en vacancia |
|---|---|
| Apo3001 | Bodegas + Oficinas (no tiene Locales Comerciales en el rent roll) |
| Apo4501 | Locales Comerciales + Oficinas (excluye Bodegas y Estacionamiento) |
| Apo4700 | Locales Comerciales + Oficinas (excluye Bodegas y Estacionamiento) |
| Torre A, Boulevard | todo excepto Estacionamiento (vía `v_vacancia_activo`, ya excluye parking por defecto) |
| Viña Centro, INMOSA, Sucden, Mall Curicó | fuente manual (`raw_vacancia_manual`), vía `v_vacancia_activo` |

`Estacionamiento` está excluido siempre por defecto en `v_vacancia_activo`
(no es parte del universo de vacancia comercial). Para Apo3001/Apo4501/Apo4700
hay que filtrar `v_vacancia_activo_tipo` a mano con los tipos de la tabla de
arriba en vez de usar `v_vacancia_activo` directo (que incluiría Bodegas
también).

### Query de referencia (periodo jun-2026, ejemplo)

```sql
-- Apo4501 / Apo4700: solo Locales + Oficinas
SELECT SUM(m2_gla), SUM(m2_vacantes) FROM v_vacancia_activo_tipo
WHERE activo_key = 'Apo4501' AND periodo = '2026-06'
  AND tipo_unidad IN ('Locales Comerciales', 'Oficinas');

-- Apo3001: Bodegas + Oficinas
SELECT SUM(m2_gla), SUM(m2_vacantes) FROM v_vacancia_activo_tipo
WHERE activo_key = 'Apo3001' AND periodo = '2026-06'
  AND tipo_unidad IN ('Bodegas', 'Oficinas');

-- resto de activos TRI: v_vacancia_activo directo (ya excluye Estacionamiento)
SELECT activo_key, m2_gla, m2_vacantes FROM v_vacancia_activo
WHERE periodo = '2026-06'
  AND activo_key IN ('Torre A','Boulevard','Viña Centro','INMOSA','Sucden','Mall Curicó');
```

Luego ponderar cada fila por `participacion_efectiva` de
`v_activo_fondo_efectivo` (fondo_key='TRI'), con la excepción Apo3001=1,0
**solo en el numerador** (m² vacantes), no en el denominador (GLA).

### Validado jun-2026 (post-fix)

| | Sin ponderar | Ponderado |
|---|---|---|
| m² GLA | 136.069,5 | 80.177,6 |
| m² vacantes | 7.498,9 | 4.775,5 |
| Vacancia % | 5,51% | 5,96% |

Validado contra el archivo del usuario: sin ponderar 7.499 / ponderado 4.775
(exacto); GLA sin ponderar 137.254 / ponderado 80.327 (diff ~1%, dentro de
tolerancia esperada por el usuario).
