# NOI, Ingresos, Caja Mínima, Tasa de Arriendo y Cap Rate — Metodología canónica (Apo + PT)

> Validado contra cálculo manual del usuario a MAR-2026 (tasa arriendo 5,39%, cap rate 4,58%).
> Consolidado en `derived_kpi` 2026-07-09 (Apo, variante contable) y 2026-07-13 (PT, variante
> bursátil — ver §8). TRI sigue pendiente (falta consolidar ingresos/NOI por activo).
> Ver también [[kpis_rentabilidad_fondos]] (TIR/YTD/DY) y [[activos/apoquindo]].

---

## 1. Ingresos U12M / NOI U12M (Apo)

```
ventana_u12m = últimos 12 meses terminados en el período de corte (inclusive)
ingresos_u12m = SUM(monto_clp) FROM raw_er_activo_line
                WHERE activo_key IN ('Apo4501','Apo4700')
                  AND seccion='INGRESOS_OPERACION' AND periodo IN ventana_u12m
                  AND superseded_at IS NULL
noi_u12m      = SUM(monto_clp) FROM raw_er_activo_line   -- ingresos + gastos, ya con signo
                WHERE activo_key IN ('Apo4501','Apo4700')
                  AND periodo IN ventana_u12m AND superseded_at IS NULL
```

> **Trampa de unidades**: pese al nombre de columna, `raw_er_activo_line.monto_clp` para Apo
> **está en UF, no en CLP** — la planilla fuente (`raw/NOI.xlsx`) viene en UF y
> `ingest_er_apoquindo.py` no convierte ni releibla la columna. Confirmado por magnitud
> (ingresos ~13.000-16.000/mes, imposible en CLP para este activo; consistente con UF ×
> ~39.000 CLP/UF). **No corregir la ingesta sin revisar antes** — esta wiki asume UF.

**Cobertura**: 2019-01 a 2026-05 (mensual). U12M calculable desde 2019-12 (primer trimestre
con 12 meses completos hacia atrás).

**Persistido en**: `derived_kpi` kpi=`ingresos_u12m`/`noi_u12m`, `entidad_tipo='fondo'`,
`entidad_key='Apo'`, `unidad='UF'`, 26 trimestres (2019-12 a 2026-03).

---

## 2. NOI mensual / Ingresos mensuales (Apo)

Igual que U12M pero sin ventana — un solo período:

```
ingresos_mes = SUM(monto_clp) WHERE seccion='INGRESOS_OPERACION' AND periodo = mes
noi_mes      = SUM(monto_clp) WHERE periodo = mes   -- Apo4501+Apo4700
```

**Persistido en**: `derived_kpi` kpi=`ingresos_mes`/`noi_mes`, mensual, 2019-01 a 2026-05 (89 meses).
Se usa en el factsheet para las filas "Ingresos [mes]" / "NOI [mes]" (label dinámico = mes del
período contable seleccionado).

---

## 3. Caja Mínima (los 3 fondos)

Regla de negocio del usuario (2026-07-09), % sobre activos totales del fondo:

```
caja_minima_clp = total_activo_clp × pct
pct: Apo=0.1% · PT=1% · TRI=1%
```

- `total_activo_clp` = `ESF.total_activo` de `raw_eeff_line` (fallback: `cuenta_nombre` case/plural
  insensitive — hay filas con "TOTAL ACTIVO", "Total activos", "TOTAL ACTIVOS", etc. según el
  ingestor/fuente que las cargó; no todas tienen `cuenta_codigo_canonical` poblado).
- **Cobertura real** (`ESF.total_activo` limpio, sin duplicados):
  - **Apo**: completo, 29/29 trimestres (2019-03 a 2026-03; 2026-03 ya ingestado 2026-07-09).
  - **PT**: completo salvo 2017 (el fondo no existía aún — no aplica, no es gap).
  - **TRI**: **9 periodos sin resolver** — 7 sin parseo de balance completo (solo hay ER/flujo,
    cero líneas de activo/pasivo/patrimonio: 2017-03/06/09, 2021-03/06/09, 2023-09) y 2 con filas
    de "Total activo" duplicadas sin deduplicar, 7-8 valores distintos por periodo (2024-12,
    2025-06). Detalle en [[db]] sección "Pendientes EEFF — balance histórico".

**Persistido en**: `derived_kpi` kpi=`caja_minima`, `unidad='CLP'`, formula=`caja_minima_v1`.
67 filas iniciales + Apo 2020-12 corregido (ver hallazgo §5.1) = cobertura completa de Apo.

---

## 4. Tasa de Arriendo Ajustada Contable y Cap Rate Implícito Contable (Apo)

```
denom_uf = patrimonio_libro_uf + deuda_financiera_uf − (caja_uf − caja_minima_uf)
         = patrimonio_libro_uf + deuda_financiera_neta_uf + caja_minima_uf
           (deuda_financiera_neta ya existe en derived_kpi = deuda − caja bruta)

tasa_arriendo_ajustada_contable = ingresos_u12m / denom_uf
cap_rate_implicito_contable     = noi_u12m / denom_uf
```

Fuentes de cada término (todo en UF, período contable trimestral):
- `patrimonio_libro_uf` = `precio_uf × cuotas` de `raw_valor_cuota_contable`
  (⚠️ **bug de casing**: el mismo fondo aparece con `fondo_key='Apo'` y `'APO'` según la fuente
  de ingesta — filtrar con `UPPER(fondo_key)='APO'`, nunca `fondo_key='Apo'` a secas, o se
  pierden períodos).
- `deuda_financiera_neta_uf` = `derived_kpi` kpi=`deuda_financiera_neta` (ya existente, no
  recalculado en esta sesión).
- `caja_minima_uf` = `caja_minima_clp` (§3) / `uf_dia` del período (de `raw_valor_cuota_contable`).

**Solo se calcula para fechas contables** (trimestres de cierre), nunca para meses intermedios —
regla explícita del usuario.

**Persistido en**: `derived_kpi` kpi=`tasa_arriendo_ajustada_contable`/`cap_rate_implicito_contable`,
formula=`..._v2_caja_minima`, **26 trimestres, serie completa (2019-12 a 2026-03)**.

**Valores validados MAR-2026** (calculado en DB con `caja_minima` real, exacto contra el cálculo
manual del usuario): tasa arriendo = 5,39%, cap rate = 4,58%. `ESF.total_activo` 2026-03 = usar
la fila `TOTAL ACTIVO` (65.121.454.000 CLP, = corriente + no corriente, cuadra exacto) — el mismo
`apo_2026Q1.json` trae otra fila `Total activos` = 187.625.357.000 que NO cuadra con
corriente+no_corriente y no se usó (mismo patrón de filas duplicadas que TRI 2024-12/2025-06,
§3).

**Serie histórica (dic de cada año, ejemplo)**:

| Periodo | Tasa arriendo | Cap rate |
|---|---|---|
| 2019-12 | 5,35% | 4,89% |
| 2020-12 | 5,33% | 4,76% |
| 2021-12 | 4,79% | 4,08% |
| 2022-12 | 4,42% | 3,65% |
| 2023-12 | 4,87% | 3,72% |
| 2024-12 | 4,98% | 4,03% |
| 2025-12 | 5,31% | 4,50% |

---

## 5. Otros hallazgos de esta sesión (2026-07-09)

### 5.1 Bug de versionado en `raw_eeff_line` — Apo 2020-12

La fila con el valor **correcto** de `Total activo` (42.343.358.000 CLP, replicado
consistentemente como columna comparativa en 4 reportes posteriores: 202103, 2021-06, 202109,
202112) quedó marcada `superseded_at` (inactiva), mientras la fila **incorrecta** del reporte
propio del período (125.087.458.000, de `EEFF_APO_202012.json`, con la sección "no corriente"
mal extraída) quedó como la única activa (`superseded_at IS NULL`). Cualquier query que filtre
solo por `superseded_at IS NULL` para ese período traía el valor malo. Corregido con foto EEFF
real del usuario — no se investigó la causa raíz del proceso de dedup que invirtió el flag.

### 5.2 `raw_caja` — 4 valores no calzan con la tabla histórica del usuario

Comparado 74 fechas × 3 fondos contra tabla "Caja Histórica" del usuario — 218/222 calzan exacto.
4 no calzan, **el usuario decidió dejarlos como están** (no corregir):
- PT/TRI cruzados en `2025-10-31` (columnas invertidas)
- Apo `2020-07-27`: DB=1.190.106.357 vs tabla=1.190.316.357
- TRI `2023-05-31`: DB=6.178.698.498 vs tabla=2.610.678.498

### 5.3 Origen de `raw_caja` es no trazable

`source_file='screenshot_caja_historica'` es un tag genérico, no un archivo real — no hay script
de ingesta en el repo ni commit de git asociado al `loaded_at` (2026-06-17). Probablemente
transcrito desde una imagen en una sesión anterior no documentada.

### 5.4 `raw_eeff_line` — variantes de nombre de cuenta sin canonicalizar

Varias cargas históricas (especialmente PT 2019-12/2020-12/2023-12) tienen
`cuenta_codigo_canonical IS NULL` pero `cuenta_nombre` reconocible ("Total activos" plural,
"TOTAL ACTIVO" mayúsculas). Antes de concluir que un dato "falta", buscar por nombre
case/plural-insensitive, no solo por `cuenta_codigo_canonical`.

---

## 6. Pendientes

- Extender esta metodología a **TRI** — bloqueado hasta consolidar ingresos/NOI por activo (PT
  ya extendido, ver §8).
- Resolver los 9 periodos de `ESF.total_activo` de TRI (§3) para poder calcular `caja_minima` ahí.
- Investigar la causa raíz del bug de versionado (§5.1) — podría afectar otros fondos/períodos no
  detectados aún.

---

## 8. Tasa de Arriendo Ajustada Bursátil y Cap Rate Implícito Bursátil (PT)

Apo no transa en bolsa → solo tiene variante contable (§4). PT sí transa (serie única
`CFITRIPT-E`) → se agrega la variante **bursátil**, reemplazando `patrimonio_libro` por
`market_cap` bursátil. Misma estructura de denominador que la contable (§4):

```
denom_uf = market_cap_uf + deuda_financiera_neta_uf + caja_minima_uf
         = market_cap_uf + deuda_uf − (caja_consolidada_uf − caja_minima_uf)

tasa_arriendo_ajustada_bursatil = ingresos_u12m / denom_uf
cap_rate_implicito_bursatil     = noi_u12m / denom_uf
```

**Signo de caja confirmado con el usuario 2026-07-13**: se resta `(caja_consolidada − caja_minima)`,
no al revés — más caja consolidada disponible reduce el denominador (EV estándar); `caja_minima`
se sigue sumando de vuelta como reserva no disponible. Igual convención que la contable (§4).

Fuentes de cada término:
- `market_cap_uf` = `raw_valor_cuota_bursatil.patrimonio_bursatil_uf` (= cuotas × precio_uf,
  ya viene precalculado en la tabla), último valor disponible en el mes, `nemotecnico='CFITRIPT-E'`.
- `deuda_financiera_neta_uf` = `derived_kpi` (ya existente y mensual para PT, no recalculado).
- `caja_minima_uf` = `caja_minima_clp` (§3, extendido — ver abajo) / UF del propio trimestre en
  que se calculó, forward-filled al mes (mismo criterio `_mensual_v1` que Apo: último valor
  trimestral disponible ≤ mes).
- `ingresos_u12m` / `noi_u12m` = `derived_kpi` fondo PT, ya consolidados mensualmente (Torre A +
  Boulevard, cobertura 2018-12 a 2026-05).

**Extensión de `caja_minima` PT**: solo 10/34 trimestres estaban persistidos (2017-12 a 2019-09 +
2025-12/2026-03). Se completaron los 23 trimestres faltantes (2020-03 a 2025-09) leyendo
`ESF.total_activo` de `raw_eeff_line`, deduplicando filas corriente/no_corriente/total. Se
**excluyó 2019-12** (total activo salta a 2x el trimestre anterior y revierte al siguiente —
mismo patrón de dato inconsistente que el bug de Apo 2020-12, §5.1; no se pudo determinar cuál de
las dos posibles cifras es la correcta sin el EEFF fuente). El hueco de ese trimestre se cubre
por el forward-fill normal (usa 2019-09 hasta que 2020-03 esté disponible).

**Persistido en**: `derived_kpi` kpi=`tasa_arriendo_ajustada_bursatil`/`cap_rate_implicito_bursatil`,
`entidad_tipo='fondo'`, `entidad_key='PT'`, `unidad='ratio'`,
formula=`tasa_arriendo_ajustada_bursatil_mensual_v1` / `cap_rate_implicito_bursatil_mensual_v1`,
**90 meses, 2018-12 a 2026-05** (acotado por la cobertura de `ingresos_u12m`).

Script: `scripts/consolidate_kpis_bursatil_pt.py` (idempotente, re-ejecutable).

**Serie histórica (dic de cada año)**:

| Periodo | Tasa arriendo bursátil | Cap rate bursátil |
|---|---|---|
| 2018-12 | 5,97% | 5,17% |
| 2019-12 | 5,27% | 4,54% |
| 2020-12 | 5,18% | 4,67% |
| 2021-12 | 5,41% | 4,36% |
| 2022-12 | 5,17% | 4,38% |
| 2023-12 | 5,54% | 4,67% |
| 2024-12 | 6,77% | 5,73% |
| 2025-12 | 7,17% | 6,04% |

**Pendiente**: extender la misma variante bursátil a TRI (3 series A/C/I) cuando se consolide
ingresos/NOI por activo de TRI.

## 7. Despliegue en Fact Sheet (`factsheet.html`)

Tabla "Otros Indicadores" (`scripts/build_factsheet.py`) muestra, por fondo/período contable:
Tasa Arriendo, Cap Rate, Ingresos U12M, Ingresos [mes], NOI U12M, NOI [mes] — todos con trazabilidad
(click abre modal con fórmula/SQL/fuente, ver `KPI_META` en el script). Se llenan desde
`derived_kpi` vía `fondo_kpi` (query en `build_fund_data`, kpis sin `variante`). Por ahora solo
Apo tiene datos; PT/TRI muestran "—" hasta hacer el mismo trabajo.
