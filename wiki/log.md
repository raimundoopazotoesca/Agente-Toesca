# Log — Wiki Agente Toesca

> Log cronológico append-only. Una entrada por operación.
> Parsear últimas entradas: `grep "^## \[" wiki/log.md | tail -10`

## [2026-07-13] doc+regla | Supuestos prospectivos ER/NOI Fondo PT

Definidos por usuario para cálculos futuros de ingresos/NOI PT, sin tocar la DB histórica:
desde 2026-07 en adelante `tools/db/ingest_er_pt.py` aplica administración como gasto de
0,2% de ingresos operacionales por activo; GC vacancia Boulevard/Inmob. CDC = 531 UF mensual;
contribuciones fijas Torre A = 1.257 UF mensual y Boulevard = 621 UF mensual; seguros fijos
Torre A = 173,464166666667 UF mensual y Boulevard = 63,46 UF mensual. Todos se guardan como
gastos negativos.

La ingesta queda protegida para no supersedear períodos históricos cuando ya existen filas PT
activas anteriores a 2026-07. Pendiente PT: Margen Energía.

## [2026-07-13] seguridad/fix | Auditoría integral de código, esquema e interfaces

Auditoría completa del estado actual. Se corrigió la cadena de migraciones para
DB nuevas y se hizo atómica por archivo; importar el agente ya no migra la DB de
negocio. Se preparó migración 048 para deduplicar `derived_kpi` cuando
`variante IS NULL`, sin aplicarla a la DB canónica (continúa en v46).

Se confinaron rutas de archivos a sus raíces autorizadas, se bloquearon las
herramientas de autoedición del modelo, se filtran herramientas mutables según
la intención original y se reforzó el prompt contra instrucciones embebidas en
correo/documentos. El servidor Flask ahora requiere bearer token, escucha en
localhost y limita tamaño/concurrencia; Streamlit exige `AUTH_COOKIE_KEY` externo.

También se corrigieron escrituras a vistas legacy (`fact_uf`, `fact_dividendo`,
tablas `_line`), idempotencia de ER/KPI/dividendos, conservación de fechas
diarias y migración v1→v2 segura. El extractor CDG antiguo que infería columnas
y nemotécnicos erróneos quedó deshabilitado. Dependencias directas completadas y
`lxml` actualizado a 6.1.0. Verificación: 124 tests pasan, 1 omitido; compilación,
Ruff F821, `git diff --check` y `pip-audit` sin hallazgos.

## [2026-07-13] feat | Tasa arriendo ajustada bursátil y cap rate implícito bursátil — Fondo PT

Nuevo script `scripts/consolidate_kpis_bursatil_pt.py`, réplica de la metodología ya validada
para Apo (contable, [[kpis_noi_cap_rate_apo]] §4) pero con `market_cap` bursátil en vez de
`patrimonio_libro` (Apo no transa en bolsa, PT sí). Denominador = market_cap + deuda_financiera_neta
+ caja_minima (signo confirmado con el usuario: se resta caja_consolidada − caja_minima, no al
revés — EV estándar).

Como parte del mismo trabajo se extendió `caja_minima` de PT: solo 10/34 trimestres estaban
persistidos, se completaron 23 más desde `ESF.total_activo` (`raw_eeff_line`, dedup de filas
corriente/no_corriente/total). Se excluyó 2019-12 por dato inconsistente (total activo salta 2x
y revierte, sin poder determinar la cifra correcta sin el EEFF fuente).

Persistido en `derived_kpi`: `tasa_arriendo_ajustada_bursatil` / `cap_rate_implicito_bursatil`,
fondo PT, 90 meses (2018-12 a 2026-05). Detalle completo en [[kpis_noi_cap_rate_apo]] §8.
Pendiente: misma variante para TRI cuando se consolide ingresos/NOI por activo de TRI.


## [2026-07-13] ingesta | ER/NOI Fondo PT (Torre A + Boulevard) desde NOI PT.xlsx

Nuevo ingestor `tools/db/ingest_er_pt.py`. Persiste 945 líneas en `raw_er_activo_line`
para activos `Torre A` y `Boulevard` (fondo PT), períodos 2018-01 a 2026-05.
Valores en UF, guardados en `monto_clp` por convención (igual que Apoquindo).
NOI derivado on-demand; ene-25 = 13.478,69 UF (imagen: 13.479 ✓).

Pendientes de automatización documentados en el ingestor:
- Margen Energía Torre A y Blvd: calculado internamente en Toesca (urgencia baja)
- Gasto Común Vacancia: fórmula pendiente de definición (urgencia media)
- Seguros: fórmula pendiente (urgencia media)
- Contribuciones: actualmente viene de la planilla; fórmula hardcoded documentada
  (Torre A: (-110660042-39543299)/UF/3, Blvd: (-54388202-19886599)/3/UF)


## [2026-07-09] doc+fix | Metodología NOI/caja mínima/tasa arriendo/cap rate consolidada (Apo) + cierre 2026-03

Nueva página [[kpis_noi_cap_rate_apo]] con toda la metodología aprendida en la sesión: fórmulas de
`ingresos_u12m`/`noi_u12m`/`ingresos_mes`/`noi_mes`/`caja_minima`/`tasa_arriendo_ajustada_contable`/
`cap_rate_implicito_contable`, más los 4 hallazgos de datos (bug versionado Apo 2020-12, 4 valores
de `raw_caja` no corregidos por decisión del usuario, origen no trazable de `raw_caja`, variantes
de nombre sin canonicalizar en `raw_eeff_line`). Enlazada desde `wiki/index.md`.

Con el EEFF Apo 2026-03 ya ingestado (ver entrada siguiente), se cerró el último trimestre
pendiente: `caja_minima` (65.121.454 CLP, usando la fila `TOTAL ACTIVO`=65.121.454.000 — el JSON
también trae una fila `Total activos`=187.625.357.000 que no cuadra con corriente+no_corriente y
se descartó) y recalculados `tasa_arriendo_ajustada_contable`/`cap_rate_implicito_contable` para
2026-03: **5,39% / 4,58%**, exacto contra el cálculo manual del usuario. Serie ahora completa:
26/26 trimestres, 2019-12 a 2026-03.

Desplegado en `factsheet.html`: tabla "Otros Indicadores" (antes 100% placeholder para los 3
fondos) ahora dinámica — Tasa Arriendo, Cap Rate, Ingresos U12M/mes, NOI U12M/mes, con trazabilidad
(modal formula/SQL). Fix incluido: el label "Ingresos/NOI [mes]" no mostraba el mes real porque el
reemplazo de `.oi-mes` corría antes de insertar esas filas en el DOM — resuelto interpolando el mes
directo en el template en vez de depender de un span reemplazado después.

## [2026-07-09] ingesta | Apo EEFF 2026-03 completa — ESF, valor cuota, capital suscrito

Ingestionado desde JSON parseado de PDF (ChatGPT):
- `raw_valor_cuota_contable`: valor_cuota_libro_uf=0.700085245, cuotas=1.585.000
- `raw_eeff_line` (ESF línea a línea): total_activo=CLP 65.121M, total_pasivo=CLP 20.911M, patrimonio=CLP 44.209M
- `raw_capital_suscrito`: capital_acumulado=980.794,96 UF

Sin dividendos ni disminuciones en el período (confirmado en notas del PDF).
**Pendiente aún**: ESF línea a línea TRI (7 períodos 2017-2023) + 2 períodos 2024-12/2025-06 con duplicados.

## [2026-07-09] fix+pendiente | caja_minima consolidada + gaps de balance EEFF (TRI, Apo 2026-03)

Consolidados en `derived_kpi`: `ingresos_u12m`/`noi_u12m`/`tasa_arriendo_ajustada_contable`/
`cap_rate_implicito_contable` para fondo Apo (26 trimestres, 2019-12 a 2026-03) y `caja_minima`
(% de activos totales: Apo 0.1%, PT/TRI 1%) para los 3 fondos donde `ESF.total_activo` existe limpio.
Validado exacto contra cálculo manual del usuario a mar-2026 (tasa arriendo 5,39%, cap rate 4,58%).

Al auditar cobertura de `ESF.total_activo` aparecieron 3 hallazgos:
1. **Bug de versionado en Apo 2020-12**: la fila correcta (comparativa en 4 reportes posteriores,
   42.343.358.000) quedó `superseded_at` mientras la incorrecta del reporte propio
   (125.087.458.000) quedó viva. Corregido con foto EEFF del usuario.
2. **raw_caja tiene 4 valores mal cargados** vs. tabla histórica del usuario: PT/TRI cruzados en
   2025-10-31, Apo 2020-07-27 y TRI 2023-05-31 con dígitos distintos. Usuario decidió NO corregirlos
   por ahora.
3. **TRI: 9 periodos pendientes** de `ESF.total_activo` — 7 sin parseo de balance completo
   (2017-03/06/09, 2021-03/06/09, 2023-09) y 2 con filas duplicadas sin resolver (2024-12, 2025-06).
   Detalle completo en [[db]] sección "Pendientes EEFF — balance histórico". **Apo 2026-03** también
   pendiente de ingesta.

## [2026-07-09] ingesta | ER Fondo Apoquindo (Apo4501, Apo4700) desde planilla local raw/NOI.xlsx

Mientras no llegan las respuestas de las APIs de JLL y Tres Asociados, se pobló `raw_er_activo_line`
con el ER histórico de Apo4501/Apo4700 (2019-01 a 2026-05, 1405 filas, 10 categorías por activo/mes).
Ingestor nuevo: `tools/db/ingest_er_apoquindo.py`. NOI verificado exacto contra CDG (dic-24 a jun-25).
Fix incluido: `dim_activo.participacion_fondo_activo` = 1.0 para Apo4501/Apo4700 (antes 0.3 por
confundir la relación fondo-fondo TRI→Apo con la relación fondo-activo; migración 047). Contribuciones
viene combinada (sin desglose por edificio) en 10 meses históricos (2019-01 a 2019-10; el resto del
histórico sí trae desglose real y se respetó tal cual) — split 25% Apo4700/75% Apo4501 aplicado solo
donde falta el desglose, misma proporción que la fórmula acordada para meses futuros sin dato: `(-165.941.575-62.167.695)/3/UF_mes`. Detalle en [[activos/apoquindo]] y
`docs/superpowers/specs/2026-07-09-apoquindo-er-ingesta-design.md`.

## [2026-07-02] feat | duration_deuda v2 — metodología Toesca validada, TRI look-through

Reescrita duration con la fórmula Excel de Toesca: [Σ(meses×cuota_total)/Σ(cuota_total)]/12 sobre
raw_amortizacion (cuota = capital+intereses, solo períodos futuros). Validado exacto: PT 3.391 ✓,
Apo 0.743 ✓ (CONSOLIDADO_{PT,Apo}). TRI usa look-through ponderado de créditos individuales
(no CONSOLIDADO_TRI — su capital_uf está congelado para dy_amort, no tocar): DB da 5.438 vs 5.450
de Toesca — diferencia explicada por 3 errores en el consolidado manual del usuario (hoja
'tabla tri': cuota Apo3001 duplicada 2×/3× jul-oct 2028, step-up Viña desfasado 1 mes, +1.7k
dic-2026). Los cronogramas bancarios individuales de la DB son la fuente correcta. Backfill v2
completo reemplazó v1: 932 filas (fondo 234 + activo 698), 2020-01→2026-06.

## [2026-07-02] feat | Backfill completo bloque leverage: dscr + duration_deuda historicos

Backfilleados los 2 KPIs restantes del bloque leverage en derived_kpi (2020-01..2026-06):
dscr fondo 234 + activo 415, duration_deuda fondo 234 + activo 698. Bloque completo:
ltv, ltc, deuda_consolidada, leverage_financiero, dscr, duration_deuda — todos con
historico en DB. Errores esperados en dscr activo: Apo4501/4700 sin NOI individual.

## [2026-07-02] feat | leverage_financiero (Deuda/Patrimonio) histórico + fix cuotas TRI en EEFF antiguos

Nuevo `kpi='leverage_financiero'` = deuda consolidada (look-through TRI) / patrimonio contable
(VNA×cuotas, Σ series). Solo fondo, solo cierres con VNA. Backfilleado: PT 25 pts (2020-03+),
Apo 35, TRI 9 (2021-12+). Valores 2026-03: PT 4.139, TRI 1.522, Apo 2.325.

**Fix datos**: los EEFF PDF de 2024-06/2025-03/2025-06 tenían cuotas TRI erróneas en
`raw_valor_cuota_contable` (160.000/242.161/223.948 — línea equivocada del PDF, desinflaba el
patrimonio ~5x). Corregidas a las canónicas validadas exacto contra `raw_ar_event`
(aportes−canjes): A 475.667, C 1.252.928, I 1.091.101. Además dedup de 26 filas duplicadas
(`superseded_at NULL`) en cierres de año; grupo A/2021-12 tenía una fila con cuotas pre-canje
(502.869) — conservada la post-canje (475.667). Sin duplicados restantes.

## [2026-07-02] feat | Leverage financiero consolidado: LTV, LTC, deuda_consolidada históricos en derived_kpi

Implementados en el skill real-estate-finance-expert (`scripts/leverage.py`) y backfilleados
2020-01→2026-06 en `derived_kpi`: `ltv` (fondo 234 + activo 516), `ltc` (fondo 234 + activo 516),
`deuda_consolidada` (fondo 234). También `dscr` y `duration_deuda` implementados (sin backfill aún).

**Metodología validada exacto vs Toesca 2026-03** (PT LTV 0.81225 ✓, PT LTC 0.60529 ✓, Apo LTC
0.59858 ✓): LTV = deuda / tasación (fact_tasacion, tasador='Promedio', año ≤ período);
LTC = deuda / precio compra 100% (fact_adquisicion.valor_activo_uf). PT/Apo: suma simple de sus
activos. **TRI: look-through ponderado** (`_TRI_LOOKTHROUGH`) — 0.43×INMOSA, 1×Sucden/Apo3001/Viña,
0.8×Curicó, 0.3×Apo4501/4700, ⅓ exacto×TorreA/Boulevard. INMOSA sin tasación propia → suma de 6
residencias; en adquisición → lump-sum 'INMOSA' (5 residencias) + fila Domingo Calderón aparte.

**Errores encontrados y corregidos**: (1) cifra Toesca TRI LTC 0.52990 incluía Machalí en el
sumaproducto por error (confirmado) — valor correcto sin Machalí: 0.54480; (2)
`fact_adquisicion.valor_activo_uf` estaba inflado ÷% para activos con participación <100%
(el precio fuente ya era 100%) — corregido desde hoja 'compra' de tablaflujos.xlsx, que también
pobló los faltantes (INMOSA, Apo3001, Mall Curicó, Dom. Calderón); (3) `dim_activo` Apo3001
participación 0.685→1.0 (vía Chañarcillo 100%); (4) ingesta de tasaciones pisaba con NULL las
columnas ltv/ltc/cap_rate al re-ingestar fuentes parciales — `repo_tasacion.upsert_tasacion`
ahora usa COALESCE en columnas opcionales; (5) parser `ingest_tasaciones.py` reescrito
header-driven (soporta hoja 'Tasaciones' de tablaflujos.xlsx y layout legado).

## [2026-07-02] feature | Dashboard fondos con fact sheets dinámicos

Creado `dashboards/fondos.py`: página Streamlit estética Toesca con vista Portfolio + fact sheet dinámico por fondo (TRI/PT/Apo). Bloques: rentabilidad (derived_kpi), valor cuota, repartos U12M, endeudamiento, NOI, vacancia, tasaciones/LTV. Ver [[agente/dashboard-fondos]]. Aprendido: fact_tasacion tiene fila tasador='Promedio'; raw_dividendo tiene duplicados por doble fuente; raw_valor_cuota_bursatil no tiene superseded_at.

## [2026-07-02] feat | DY + Amortización consolidado en derived_kpi (kpi='dy_amort'), todos los fondos

Consolidados 550 valores históricos de `dividend_yield_con_amort` (bursátil), `_contable` y
`_capital` (Apo) en `derived_kpi` bajo `kpi='dy_amort'`, `variante='bursatil'/'contable'/'capital'`
— mismos rangos ya validados para `kpi='dy'`. TRI/PT: 2018-03→2026-03/06 (33 contable, 97-98
bursátil por serie/fondo). Apo: 2019-03→2026-03 (29, variante='capital').

Ambas fórmulas quedaron corregidas antes de consolidar (ver `wiki/kpis_rentabilidad_fondos.md`
sección 4.1): se agregó la variante contable (antes solo existía bursátil), se agregó la variante
`_capital` específica para Apo (denominador = capital suscrito por cuota, no VNA — Apo está muy
lejos de la par y el CDG usa ese denominador para este fondo específicamente), y se revirtió un
intento de excluir pagos de refinanciamiento del cálculo de amortización (el CDG no los excluye).

De paso se corrigieron datos reales de deuda que afectaban el cálculo: saldo de `CONSOLIDADO_TRI`
(faltaba crédito Sucden refinanciado), cronograma de `APO_APO_BTG` desde ene-2026 (estaba
desactualizado, asumía amortización gradual cuando el crédito se pagó completo en mar-2026), y se
creó `CONSOLIDADO_Apo` (no existía). Sin duplicados verificado tras consolidar. Todas las fórmulas
quedan congeladas — ver `dividend_yield.py` para la implementación.

## [2026-07-02] fix | DY + Amortización — saldo CONSOLIDADO_TRI/Apo corregido, sin excluir refinanciamiento

Agregada variante `dividend_yield_con_amort_contable` (antes solo existía bursátil) en
`dividend_yield.py`. Ambas validadas EXACTAS contra CDG (corte MAR-26): A=34.644%/18.038%,
C=35.316%/18.065%, I=20.184%/18.088% (bursátil/libro).

**Datos de deuda corregidos**: `raw_amortizacion` tenía `CONSOLIDADO_TRI` con saldo desactualizado
(faltaba `TRI_SUCDEN_BICE`, crédito refinanciado en ene-2026 — el saldo real 31-mar-26 es
3.532.590 UF, la DB mostraba 3.371.105). Parchado sumando el saldo/capital de SUCDEN_BICE a
`CONSOLIDADO_TRI` para los 120 períodos donde existe (2018-02→2028-01) — saldo ahora exacto.
Creado `CONSOLIDADO_Apo` desde cero (no existía) sumando `APO_APO_BTG` + `APO_APO_EUROAMERICA`
(89 períodos) — también exacto vs foto real (2.602.856 UF).

**Importante — decisión revertida**: se intentó excluir el pago de refinanciamiento de Sucden
(161.395 UF, dic-2025) del cálculo de amortización para `dividend_yield_con_amort`, razonando que
un refinanciamiento no representa deleveraging real. El usuario confirmó inicialmente ese criterio,
pero al comparar contra el CDG real se determinó que el propio CDG **no excluye** ese pago — usa
`capital_uf` de `CONSOLIDADO_{fondo}` tal cual viene de la planilla fuente. Se revirtió la
exclusión: `capital_uf` de `CONSOLIDADO_TRI` quedó en su valor ORIGINAL (sin sumar ni restar
Sucden) — el saldo (`saldo_uf`) sí se mantiene corregido con Sucden incluido, porque para ESE
campo la corrección sí calzó exacto contra la foto real del usuario. Es decir: mismo crédito, dos
tratamientos distintos según el campo (saldo sí se corrige, flujo de capital no se toca) — contra-
intuitivo pero validado dígito por dígito. **No volver a excluir sin nueva validación explícita.**

Pendiente: el archivo fuente de `CONSOLIDADO_TRI`/`CONSOLIDADO_Apo` usado por
`tools/db/ingest_financing.py` sigue desactualizado (parche aplicado directo en DB, no en el
Excel origen) — si se re-corre la ingesta completa desde ese Excel sin actualizarlo primero, se
pierde este parche.

## [2026-07-02] fix | Dividend Yield — limpieza de datos Apo, sin cambio de fórmula

`dy_v2` (`scripts/compute_kpis_series.py`) ya estaba correcto y validado exacto contra CDG para
TRI y PT (A=2.152%/4.134%, C=2.375%/4.644%, I=2.468%/2.754% mar-26). Al revisar Apo se encontró
inconsistencia de datos (no de cálculo):

1. `SERIES_CONFIG` guardaba el DY de Apo bajo `entidad_key='APO-UNICA'`, distinto al resto de
   `derived_kpi` (TIR/YTD/U12M usan `entidad_key='Apo'`, igual a `dim_serie.nemotecnico`) —
   corregido en el script (ahora usa `'Apo'` directamente, sin `nemo_db` override).
2. Existían 34 filas viejas (`Apo`/`dividend_yield_contable`, `Apo`/`dividendo_por_cuota`) de un
   proceso anterior que SÍ incluía `tipo='disminucion'` en el numerador — la fórmula validada
   (`dy_v2`) filtra solo `tipo='dividendo'`, igual que el CDG. Estas filas daban valores
   distintos (ej. dic-2020: 5.418% vs 2.304% correcto) para el rango 2020-12→2022-09, donde Apo
   tuvo varios eventos de disminución. Borradas.

Migradas las 29 filas de `APO-UNICA`/`dy` a `entidad_key='Apo'`. Sin duplicados tras la limpieza.
Re-corrido `compute_kpis_series.py --kpi dy` para confirmar que el script corregido reproduce
exactamente lo mismo.

## [2026-07-02] feat | Rentabilidad U12M — validada (bug de Excel en PT confirmado, no se replica)

Verificado `tir_contable_u12m`/`tir_bursatil_u12m` (ya existían en `tir.py`, sin cambios de código)
para las 5 series/fondos, corte MAR-2026. TRI y Apo calzan exacto contra referencia previa
(wiki `kpis_rentabilidad_fondos.md`: A=9.12%/C=9.25%/I=9.30% libro). PT NO calzaba al inicio
(mío 20.989%/9.963% vs CDG 16.673%/5.830%) — se reconstruyó la fórmula de Excel (`P10`,
`XIRR(OFFSET(Libro 12M,...))`) celda por celda y se descubrió que el CDG **omite el dividendo
29-abr-2025 de PT por orden de filas** (mismo patrón que el bug ya documentado en Serie I:
un dividendo pagado poco después del VNA de inicio queda posicionado antes en la tabla y las
fórmulas basadas en offset de fila lo saltan). El usuario confirmó explícitamente: "eso es un
error mío. El cálculo correcto debería incluirlo" — se mantiene el valor completo (con el
dividendo), NO se replica el bug. Sin cambios de código necesarios.

Consolidado en `derived_kpi`: 512 filas (TRI contable 30/serie, TRI bursátil 89/serie, PT
contable 30 + bursátil 90, Apo contable 35). Mismo rango que YTD por fondo.

## [2026-07-02] fix | Rentabilidad YTD anualizada — fórmula corregida, congelada, consolidada

Corrección importante: la metodología "YTD acumulada" documentada previamente en
`wiki/kpis_rentabilidad_fondos.md` sección 2 estaba MAL — asumía retorno simple sin anualizar,
achacando el delta de ~0.017pp vs CDG a "ruido de planilla". Al pedir la fórmula real de Excel
al usuario se descubrió: `=(1+TIR.NO.PER(flujos;fechas))^(MES(fecha_corte)/12)-1` — un XIRR
estándar (T0=31-dic año anterior, dividendos reales, Tn=corte) seguido de un ajuste por MESES
CALENDARIO (no por días). El "ruido" era en realidad la diferencia entre exponente días/365
(≈0.2466 para marzo) y exponente meses/12 (0.25 exacto) — un error de método, no ruido de datos.

Implementada como `_calcular_rent_ytd` en `tir.py`, kpis `rent_ytd_contable`/`rent_ytd_bursatil`,
validada EXACTA contra el CDG (corte MAR-2026) para las 5 series/fondos (TRI A/C/I, PT, Apo).
Congelada — no volver a tocar sin nueva validación explícita del usuario.

Consolidado en `derived_kpi`: TRI contable 2018-03→2026-03 (33/serie), TRI bursátil
2018-03→2026-06 (96/serie), PT contable 33 + bursátil 96, Apo contable 2020-03→2026-03 (35).
Total 551 filas. Primer período de cada serie (2017-12) queda sin YTD porque no existe un
31-dic-2016 previo en la DB para usar como T0 — comportamiento esperado, no error.

## [2026-07-02] fix | TIR desde inicio PT y Apo — método agregado, corrección de datos faltantes

Extendida la metodología agregada (validada para TRI bursátil el mismo día) a PT y Apo, para
AMBOS trackeos (contable y bursátil) — ver `wiki/tir_contable_desde_inicio.md`. Validado exacto
contra planilla del usuario (hojas PT/APO de `tablaflujos.xlsx`, corte MAR-2026): PT
contable=-5.121%, PT bursátil=-6.322%, Apo contable=-1.912%.

Datos faltantes agregados a `raw_ar_event`: Apo no tenía NINGUNA fila (0 aportes registrados,
faltaba el aporte único 2019-01-02 de 1.585.000 UF); PT le faltaban 2 Disminuciones
(2019-10-09, 2019-12-30). Cuidado: varias Disminuciones de PT ya estaban fusionadas dentro de
filas `tipo='dividendo'` de `raw_dividendo_line` — insertarlas de nuevo en `raw_ar_event` duplicó
el flujo hasta que se detectó comparando contra la planilla fila por fila.

Bug de dispatch encontrado y corregido en `_calcular_tir_por_cuota`: la condición original
(`COUNT(Aporte WHERE fecha >= primer_VNA) == 0` → usar método simple) fallaba para Apo porque su
único aporte coincide exactamente con la fecha del primer VNA (`fecha >= ` lo cuenta como
"posterior"). Reemplazada por `COUNT(Aporte total) <= 1` — no afecta a TRI (16/14/7 aportes cada
serie).

Consolidado en `derived_kpi`: PT contable trimestral 2017-12→2026-03 (34), PT bursátil mensual
2017-12→2026-06 (97), Apo contable 2019-03→2026-03 (39, quarterly hasta 2024-12 luego mensual).
Apo bursátil no aplica (`transa_bolsa=0`).

## [2026-07-02] feat | TIR desde inicio (contable + bursátil) consolidada en derived_kpi, TRI A/C/I

Implementadas y validadas exacto contra CDG (planilla `tablaflujos.xlsx`, corte MAR-2026) dos metodologías
**distintas y congeladas** para `tir_contable_desde_inicio` / `tir_bursatil_desde_inicio` — ver
`wiki/tir_contable_desde_inicio.md`. Contable: `_calcular_tir_por_cuota` (UF/cuota, divisor fijo, ya
validada previamente). Bursátil: `_calcular_tir_bursatil_agregado` (UF agregadas de la serie, sin
divisor — reconstruye la fórmula real de Excel `TIR.NO.PER(Tabla1[Bolsa Inicio <serie>])`).
Bug encontrado en la planilla del usuario: Serie I bursátil omite un dividendo real (29-dic-2021) en su
columna `Bolsa Inicio I2` — mismo patrón que el bug ya conocido en TIR U12M serie I. Se persistió el
valor corregido (-0.733% en MAR-26), no el de la planilla (-0.883%).

Consolidado en `derived_kpi`: contable trimestral 2019-12→2026-03 (excluidos 2017-12→2019-09 por
divisor fijo antes de terminar rondas de aportes — ver metodología), bursátil mensual 2017-12→2026-06,
78+291 filas, series CFITOERI1A/C/I. Bug de duplicación encontrado y corregido en
`_common.py::upsert_derived_kpi` (SQLite no deduplica `UNIQUE` con `variante IS NULL`; ahora hace
DELETE+INSERT explícito). Nota: Serie I bursátil muestra una caída real de precio abr→may-2026
(0.7347→0.2709 UF/cuota, confirmada en 3 fechas de transacción) — no es error de datos, pendiente de
entender la causa.

## [2026-06-11] feat | ingesta EEFF PT en raw_eeff_line completa 2020–2025

Ingesta manual de EEFF trimestrales PT (fondo paraguas, no el activo) desde PDFs vía ChatGPT → JSON → DB.
Períodos completados: 2020-03-31 a 2025-12-31 (24 períodos, 100 filas c/u).
Script: `tools/db/ingest_eeff_pt_json.py` (función `ingest_from_file`).
JSONs staging en `work/eeff_pt_json/`.

## [2026-06-11] feat | ingesta PT — raw_valor_cuota_line, dividendos, cuotas, precios

Inicio de poblamiento de DB para fondo PT (Toesca Rentas Inmobiliarias PT, CFITRIPT-E, Serie Única).

**Fuentes:**
- `A&R PT` del CDG → dividendos, VR Contable (valor cuota libro trimestral desde 2017-11), cuotas en circulación (siempre 1.640.000), precios bursátiles históricos, patrimonio bursátil.
- PDFs EEFF en `work/eeff_pt/` → valor cuota libro exacto por trimestre (tienen precedencia sobre CDG).

**Nuevo código:**
- `tools/db/ingest_cdg_extract.py::ingest_ar_pt` — lee hoja 'A&R PT' del CDG en un pase.
- `tools/db/ingest_eeff_pt.py` — parser regex EEFF PT para SERIE ÚNICA. Maneja formato 2017 ("tiene un valor cuota de\n$X") y formato 2025 ("tienen un valor cuota de $ X").
- `tools/db/backfill.py` → dominios `eeff_pt` y `ar_pt` registrados.

**Carpeta staging:** `work/eeff_pt/` — subir PDFs aquí sin subcarpetas.

**Validación:** 5 PDFs (2017-12 → 2018-12) parseados. VC cross-check vs CDG: ✓ (25.815,4355 dic-2017).

**Pendiente:**
- Subir PDFs 2019→2025 a `work/eeff_pt/` y re-correr `python -X utf8 -m tools.db.backfill eeff_pt`.
- Cuotas de PDFs no parseadas (formato tabular antiguo, Suscritas sin número en línea siguiente) — el CDG las cubre vía `ar_pt`.
- Validar resultado final del backfill `ar_pt` (CDG tiene 33 fechas VR Contable desde 2017-12).

## [2026-06-11] fix | dim_credito — fechas DD-MM-YYYY corregidas (bug ingesta)

Todas las `fecha_inicio` y `fecha_vencimiento` de `dim_credito` estaban almacenadas como
`YYYY-DD-MM` en vez de `YYYY-MM-DD` (formato chileno no convertido al ingestar).
Detectado al comparar duration PT: yo calculaba 2.43 años (con venc. ene-2029),
usuario tenía 3.17 años (con venc. nov-2029 = fecha correcta).
Fix: `scripts/fix_fechas_credito_apply.py` corrigió 23 valores en 15 créditos (PT, TRI, Apo).
PT vencimiento corregido: `2029-01-11` → `2029-11-01`. Duration PT: 3.12 años (Macaulay).
Prevención futura: parsear fechas chilenas con `dayfirst=True` al re-ingestar.

## [2026-06-08] dominio | TRI: sin dividendos en Q4-2023 ni en 2024 — confirmado por usuario

## [2026-05-27] feat | Extractor Groq EEFF TRI — independencia del CDG

Nuevo módulo `tools/db/ingest_eeff_tri_groq.py` (llama-3.3-70b-versatile via Groq):
extrae valor cuota libro, cuotas en circulación, capital/aportes/disminuciones y dividendos
desde PDFs de EEFF TRI. Fix bug regex (capturaba primer valor de tabla en vez del TOTAL).
Dedup: `tools/db/dedup_eeff_tri.py` supersede redundantes, DB sin duplicados.
Estado: 17/32 PDFs procesados (límite diario 100k tokens free tier). 15 PDFs pendientes
para próxima sesión. Validación 52/56 comparaciones EEFF vs CDG = 0.00% diff exacta;
2025-12-31 EEFF correcto (31.869), CDG tenía error (35.791) ya supersedido.
Pendiente: test capital+dividendos, backfill 15 PDFs restantes.

## [2026-05-27] refactor | Limpieza CDG legacy + pipeline ingesta DB-centric

Eliminados módulos CDG-write (`noi_tools`, `vacancia_tools`, `datos_fs_tools`, `caja_tools`, `input_tools`, `balance_consolidado_tools`) — 7.319 líneas, 32 tools desregistradas. Funciones de ingesta a DB recuperadas a `tools/db/ingest_er.py` y `tools/db/ingest_flujo.py`. Nuevo: `tools/db/coverage.py` (audit de gaps), `tools/db/ingest_router.py` (tool `ingestar_archivo` con detección por nombre), `scripts/ingest_eeff.py` generaliza a TRI/PT/APO, migración 010 con índices. System prompt explícito: DB es fuente primaria. Doc: `docs/ingest_pipeline.md`.

## [2026-05-27] skill | real-estate-finance-expert completado y integrado en agent

Skill custom finalizado para computar KPIs financieros derivados desde agente_toesca.db con caching inteligente. Aprobado evaluación (100% pass-rate, 55.6% mejora sobre baseline). Ubicación: `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\`

**Integración en agent.py** (2026-05-27):
- Wrapper `tools/finance_tools.py` que invoca compute_or_fetch desde la skill
- 4 nuevas herramientas registradas en `tools/registry.py`:
  - `calcular_indicador`: invoca compute_or_fetch (kpi, entidad_tipo, entidad_key, periodo)
  - `listar_indicadores`: lista KPIs disponibles (8 operativos + 3 placeholders)
  - `invalidar_cache_indicador`: invalida cache para un KPI
  - `verificar_skill_finanzas`: diagnostica disponibilidad de la skill
- Herramientas agregadas a `_TOOLS_GENERAL` → siempre disponibles para agent
- Test: calcular_indicador computa 6.63% CAGR para TRI Serie A (2026-04)

Indicadores operativos: rent_desde_inicio/anualizada/u12m (CAGR), dividend_yield ±amort, cap_rate real/implícito, tasa_arriendo_uf_m2. Placeholders: TIR/XIRR, LTV/DSCR (requieren deuda), valuaciones.

Arquitectura: three-tier loop (read cache → compute → persist si criteria). Recipe versioning `<kpi>_v<base>_<override_hash>` con invalidación automática al editar `config/formulas.yaml`. Fórmulas editables sin tocar Python.

## [2026-05-25] feat | DB Fase 2 — backfill histórico completo

`tools/db/backfill.py` pobló la DB desde archivos ya en SharePoint/CDG (idempotente, reusa los `_persist_*`):
- rent_roll: 10.122 filas (2025-09..2026-03, 5 activos)
- er_activo: 400 (Viña/Curicó, 2025-12..2026-03)
- flujo INMOSA: 46 (2026-01..02; marzo "Senior Assist" queda al flujo en vivo)
- uf: 5.182 días (2012..2026, hoja UF del CDG)
- precios: 100 (4 nemos × 25 meses, datachart LarraínVial)
- valor_cuota_libro (eeff): 4 trimestres (regex parcial)
- dividendos: 108 en fact_dividendo (PT+Rentas) + 6 Apoquindo en derived_kpi (desde CDG)

Detalle técnico: `_persist_flujo_lines` ganó `hash_extra` para archivos multi-período (INMOSA).
Query tools ampliadas con `consultar_db_dividendos`. 81 tests verdes. Ver `wiki/db.md`.

## [2026-05-25] feat | DB Fase 1 — dual-write de 5 dominios

Cada tool de ingesta ahora escribe en paralelo a la DB (best-effort, no rompe Excel si la DB falla):
- `web_bursatil_tools.obtener_precio_cuota` → `fact_precio_cuota`
- `eeff_tools.leer_eeff` → `derived_kpi` (valor_cuota_libro; serie A/C/I por nemotécnico, fondo único para PT/Apoquindo)
- `noi_tools._actualizar_er_mall` (Viña/Curicó) → `raw_er_activo_line`
- `noi_tools.actualizar_noi_inmosa` → `raw_flujo_line`
- `rentroll_tools.consolidar_rent_rolls` → `raw_rent_roll_line` (por arrendatario, mapeo Activo1→activo_key para los 5 activos)

Idempotencia por (file_hash, source_row). 69 tests verdes. Ver `wiki/db.md` para estado y pendientes.

## [2026-05-25] feat | DB Fase 0 — esqueleto SQLite del agente

Se creó la base de datos real del agente (migración desde Excels como "base de datos"):
- `tools/db/` con capa de acceso por dominio: `connection.py` (migraciones idempotentes), `errors.py`, y repos `repo_fondo`, `repo_audit`, `repo_rent_roll`, `repo_eeff`, `repo_flujo`, `repo_er_activo`, `repo_fact`, `repo_kpi`.
- Schema versionado en `tools/db/migrations/` (001 dim, 002 raw, 003 facts, 004 derived, 005 audit, 006 seeds). 4 capas: dimensiones, raw (línea-a-línea del proveedor con linaje + hash idempotente), facts (precios/UF/dividendos), derived_kpi (formato largo para dashboards), audit (ingest_run/publish_run).
- Migraciones se aplican automáticamente al cargar `tools/memory_tools.py`.
- Seeds de 3 fondos, 6 activos, 4 series desde catálogos antes hardcoded.
- 48 tests, todos verdes. Backup pre-fase0 en `memory/backups/`.

Excels siguen siendo la verdad (entregable). DB lista para Fase 1 (dual-write por dominio).
Spec: `docs/superpowers/specs/2026-05-25-db-migration-design.md`. Plan: `docs/superpowers/plans/2026-05-25-db-fase0-esqueleto.md`.

## [2026-05-12] feat | EERR Viña Centro implementado en Balance Consolidado Rentas Nuevo

`VINA_EERR_MAP` (73 filas) en `tools/balance_consolidado_tools.py`. Fuente: hoja `BALANCE ACUMULADO` del INFORME EEFF Viña. Mapeado por descripción/valor en vez de strictly por label code: 7 filas re-mapeadas (94, 97, 113, 119, 120, 123, 137) por desalineación entre label y chart of accounts real del TB. Verificado Dec 2025: total G-Pd = 3.093.097.786 = D189 histórico (2.848.461.407) + D194 control (244.636.379) — el map nuevo elimina ese descuadre histórico de 244M. 0 cuentas EERR del TB quedan sin mapear. Wireado reemplazando `EERR: TODO` en `actualizar_balance_consolidado_rentas_nuevo`.

## [2026-05-12] feat | EERR Curicó implementado en Balance Consolidado Rentas Nuevo

`CURICO_EERR_MAP` (57 filas) en `tools/balance_consolidado_tools.py`. Códigos extraídos de los labels en col B filas 76-168 hoja `Curicó` del vF. Fuente: hoja `Acum MM-AAAA` del informe Curicó (misma que el balance). Verificado vs trial balance Dec 2025: resultado del período -405.776.897 calza con D174 histórico, 0 diferencias en las 57 filas. Wireado en `actualizar_balance_consolidado_rentas_nuevo` reemplazando el `EERR: TODO`. Fila 162 (`4-2-01-004`) duplica la 94 — se omite.

## [2026-05-11] feat | EERR Chañarcillo implementado en Balance Consolidado Rentas Nuevo

`CHANAR_EERR_MAP` (31 filas) en `tools/balance_consolidado_tools.py`. Códigos extraídos de los labels en col B filas 76-116 de la hoja Chañarcillo. Verificado vs trial balance Dec 2025: resultado del período 470.785.569 calza con D119 histórico.

**Observación importante:** los valores históricos en col D del planilla estaban desalineados respecto a sus labels — quien llenaba históricamente puso COMISIONES en la fila labelada ESTRUCTURACION, etc. (7 filas afectadas, rango 93-99). El nuevo map sigue el código del label (criterio contable correcto), por lo que los valores escritos en esas filas cambiarán respecto al histórico.

**Pendiente identificado:** bug `_copy_vals_sheet_rn` falla con `'MergedCell' object attribute 'value' is read-only` al copiar Resumen PT/Apoquindo. Hay que saltar celdas merged.

## [2026-05-11] fix | INMOSA — distinguir ER-FC vs Balance General + reconocer naming nuevo

Dos archivos distintos compartían carpetas mal asignadas:
- **ER-FC INMOSA** (estado de resultado + flujo de caja) → `INMOSA/Flujos/` — usado por CDG/NOI-RCSD.
- **Balance General Senior Assist** → `INMOSA/Contabilidad/` — usado por balance consolidado.

Desde 2026 el ER-FC viene nombrado `EEFF y FC Senior Assist Mar.26.xlsx` (sin "INMOSA" ni "ER-FC" en el nombre). `raw_tools.py` lo ruteaba a Contabilidad por matchear "senior assist", y `buscar_er_inmosa` no lo encontraba (filtraba por `"inmosa" in nombre`).

Cambios:
- `tools/raw_tools.py`: ruta ER-FC si nombre contiene "EEFF/FC" + "Senior Assist"; ruta Contabilidad solo si contiene "Balance" + "Senior Assist".
- `tools/noi_tools.py::buscar_er_inmosa`: matchea "inmosa" o "senior assist", excluye "balance".
- `tools/gestion_renta_tools.py`: el chequeo de "mes en filename" fallaba ("Ene a Feb" no implica que falte marzo). Ahora solo se valida existencia.
- Archivo `EEFF y FC Senior Assist Mar.26.xlsx` movido de Contabilidad/2026 → Flujos/2026.

## [2026-05-07] feat | Balance Consolidado Rentas Nuevo — implementación parcial

Implementada `actualizar_balance_consolidado_rentas_nuevo(mes, año)` en `tools/balance_consolidado_tools.py`.
Balance de 4 entidades (Chañarcillo, Curicó, Inmob VC, Viña Centro) + EERR Inmosa desde Senior Assist.
Copy de hojas PT/Apoquindo desde sus vAgente. Pendiente: EERR de 4 entidades, balance Inmosa Q1-Q3, Fondo Rentas PDF.
Instrucciones completas en `wiki/procesos/balance-consolidado-rentas-nuevo.md`.

---

## [2026-05-07] reorganización | SharePoint restructurado + carpeta RAW + raw_tools

- Nueva estructura: `Fondos/{Rentas Apoquindo|Rentas PT|Rentas TRI|Renta Residencial}/` agrupa EEFF, Fact Sheets y activos por fondo
- Activos de TRI (Viña, Curicó, INMOSA) ahora en `Fondos/Rentas TRI/Activos/{activo}/{EEFF|Rent Roll}/`
- CDG mensual: estructura canonica en `Control de Gestión/CDG Mensual/`
- Saldo Caja, Balances, TIR bajo `Control de Gestión/`
- Carpeta `RAW/` creada: usuario sube archivos, agente llama `ordenar_archivos_raw()` para clasificarlos
- Código actualizado: 7 tool files + registry.py + raw_tools.py (nuevo)
- Bug corregido en `factsheet_tools.py`: eliminado `_INMOBILIARIO` que causaba double-nesting

## [2026-05-07] integración | Power Automate — servidor HTTP + flujos recomendados

- `run_agent()` ahora retorna `str` (antes era `None`)
- Agregado `start_server()` en `agent.py` — Flask en puerto 5000 vía `python agent.py --server`
- Endpoints: `POST /run {"instruction": "..."}` y `GET /health`
- Wiki: `integraciones/power-automate.md` con flujos PA y framework de evaluación
- Flask 3.1.3 instalado

## [2026-05-06] aprendizaje | Estructura TRI desde diagrama validado

- Registrada estructura de Toesca Rentas Inmobiliarias con sociedades, participaciones y activos finales.
- Machalí marcado como liquidado; no debe considerarse activo vigente.
- Pesos históricos del diagrama rebajados pro forma excluyendo Machalí: base 96%.
- Fuente: diagrama enviado por usuario y confirmaciones del usuario en conversación.

## [2026-05-04] aprendizaje | Balance Consolidado PT documentado

- Mapeada hoja Fondo PT: clasificaciones, unidades (M$×1000), procedimiento inserción columna
- Verificado cruce EEFF 4Q2025 → planilla: Total Activo, Patrimonio, Resultado cuadran
- Fuente EEFF: SharePoint/Fondos/Rentas PT/EEFF/{año}/{TT}/
- Fuente planilla vF: SharePoint/Control de Gestión/Balances Consolidados/
- Pendiente: mapeo Inmob Boulevard, Torre A (fuente desconocida), EEFF trimestrales

## [2026-05-01] init | Wiki creada

- Estructura inicial creada: `raw/`, `wiki/agente/`, `fondos/`, `activos/`, `procesos/`, `conceptos/`, `errores/`
- CLAUDE.md escrito con schema completo de la wiki
- `index.md` inicializado con páginas semilla basadas en CLAUDE.md del agente
- `log.md` iniciado
- Páginas semilla creadas en todas las categorías
- Fuentes ingresadas: 0 — wiki lista para primer ingest real
