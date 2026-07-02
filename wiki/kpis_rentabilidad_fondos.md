# KPIs de Rentabilidad — Metodología canónica validada

> Validado contra CDG manual (sesión jun-2026, corte MAR-2026).
> Usar siempre estas fórmulas. No inventar variantes.

---

## 1. TIR desde inicio (anualizada)

### TRI series A / C / I — método `tir_por_cuota`

```
Flujos en UF/cuota:
  Aportes   → -(monto_uf / cuotas_totales_serie)     [negativo, fecha real]
  Dismin.   → +(monto_uf / cuotas_del_evento)         [positivo, fecha real]
  Dividendos → +monto_uf_cuota                        [positivo, fecha_pago real]
  Terminal  → +precio_uf (raw_valor_cuota_line)       [positivo, fecha_corte]

XIRR = bisección sobre: Σ CF_i / (1+r)^((d_i - d_0)/365)
```

Divisores fijos (cuotas_totales = SUM(cuotas) WHERE detalle='Aporte'):

| Serie | cuotas_totales |
|-------|---------------|
| CFITOERI1A | 526,079 |
| CFITOERI1C | 1,385,310 |
| CFITOERI1I | 908,887 |

**Valores validados MAR-26 (libro):** A=0.434% · C=0.972% · I=1.072%

### PT (CFITRIPT-E) — método `tir_simple_uf`

```
T0 = primer registro en raw_valor_cuota_line tipo='contable'
Flow T0 = -precio_uf (precio implícito de la inversión)
Dividendos y terminal = igual a TRI
```

**Fuente terminal**: siempre `raw_valor_cuota_line`. NUNCA `raw_ar_event_line`.

---

## 2. Rentabilidad YTD anualizada (CORREGIDO 2026-07 — CONGELADO, ver más abajo)

> **Corrección**: la entrada anterior de esta sección (retorno simple, "no anualizar")
> estaba MAL. Reconstruida la fórmula real de Excel (usuario, 2026-07):
> `=(1+TIR.NO.PER(rango_flujos; rango_fechas))^(MES(fecha_corte)/12) - 1`.
> El header SÍ refleja un cálculo real de anualización — no es una etiqueta heredada.
> El "delta ~0.017pp" que se atribuyó a "ruido de planilla" era en realidad la
> diferencia entre exponente por días (90/365≈0.2466) y exponente por MESES
> CALENDARIO (3/12=0.25) — un error de metodología, no ruido. Ver
> `tir_contable_desde_inicio.md` (o `_calcular_rent_ytd` en `tir.py`) para el detalle.

```
flujos = [-VNA(31-dic año anterior), dividendos(fecha_pago real, en (T0, corte]), +VNA(corte)]
r_xirr = XIRR(flujos)                          # ACT/365, estándar
YTD_anualizada = (1 + r_xirr) ^ (MES(corte)/12) - 1
```

- `VNA` mismo tipo (contable/bursátil) en T0 y Tn, fecha EXACTA en `raw_valor_cuota_line`
- Dividendos: `monto_uf_cuota` (per-cuota), entran como flujo propio en el XIRR, NO se
  suman al terminal
- Aplica igual para TRI (A/C/I), PT y Apo — mismo `tipo_vr` contable/bursátil que el resto

**Valores validados MAR-26 (exacto, las 5 series/fondos):**
A: libro=1.209% / bursátil=9.822% · C: libro=1.255% / bursátil=-0.289% ·
I: libro=1.274% / bursátil=-0.289% · PT: libro=1.110% / bursátil=-0.289% ·
Apo: libro=2.298% (sin bursátil, no transa en bolsa)

---

## 3. Rentabilidad U12M (XIRR anualizado)

```
Flujos U12M en UF/cuota:
  Inicio   → -VNA_contable (fecha = 12 meses antes del corte, e.g. MAR-31 año anterior)
  Divid.   → +monto_uf_cuota (todos los pagados en el período, fecha_pago real)
  Terminal → +VNA_contable (fecha_corte)

XIRR = bisección estándar (annualiza automáticamente)
```

Filtro dividendos U12M: `fecha_pago >= fecha_inicio_u12m AND fecha_pago <= fecha_corte`
- Incluir TODOS los dividendos del período, sin excepción por número de cuotas ni otra condición

**Valores validados MAR-26 (libro, XIRR):** A=9.12% · C=9.25% · I=9.30%

> **Bug conocido CDG**: Serie I muestra 8.272% porque la fórmula Excel omite el dividendo
> ABR-29-25 (aparece en fila 512, antes del VNA MAR-25 en fila 520). El valor correcto
> es 9.30% (confirmado por el usuario jun-2026).
>
> **Mismo bug en PT (confirmado 2026-07-02)**: CDG muestra 16.673%/5.830% (libro/bursátil)
> porque omite el dividendo 29-abr-2025 (mismo patrón: fila posicionada antes del VNA de
> inicio 31-mar-2025). Valor correcto (con el dividendo): 20.989% libro / 9.963% bursátil.
> Confirmado por el usuario: "eso es un error mío. El cálculo correcto debería incluirlo."
> **Patrón general**: cuando el U12M/desde-inicio de una serie no calza con el CDG por un
> delta que desaparece al excluir un dividendo específico, sospechar primero de este bug de
> orden de filas — no ajustar la metodología propia, usar el valor completo.

---

## 4. Dividend Yield U12M

```
DY_libro   = sum(dividendos_u12m) / VNA_contable_corte
DY_bursatil = sum(dividendos_u12m) / VNA_bursatil_corte
```

- `dividendos_u12m` = todos los dividendos con fecha_pago en los últimos 12 meses
- Filtros: `tipo='dividendo'`, `superseded_at IS NULL`, `monto_uf_cuota IS NOT NULL AND > 0`
- Usa el VNA al **corte** como denominador (no el VNA de inicio)

**Valores validados MAR-26:** A=2.152%/4.134% · C=2.375%/4.644% · I=2.468%/2.754%

---

## 4.1. Dividend Yield + Amortización (CONGELADO 2026-07-02)

```
DY_amort_bursatil  = (dividendos_u12m + amort_u12m) / VNA_bursatil_corte
DY_amort_contable  = (dividendos_u12m + amort_u12m) / VNA_contable_corte
DY_amort_capital   = (dividendos_u12m + amort_u12m) / capital_suscrito_por_cuota   [solo Apo]
```

- `amort_u12m` = SUM(`capital_uf`) de `raw_amortizacion` credito_key=`CONSOLIDADO_{fondo}`,
  período (T-12m, corte], **TAL CUAL, sin excluir refinanciamientos ni pagos extraordinarios**
  (validado: el CDG no distingue — ver `dividend_yield.py::_get_amort_u12m_por_cuota`).
- Se probó excluir un pago de refinanciamiento (Sucden, TRI) y el resultado NO calzó con el
  CDG — la exclusión fue revertida. Nunca reintroducir sin nueva validación explícita.
- **Apo usa denominador distinto** (`dividend_yield_con_amort_capital`): capital suscrito por
  cuota (calculado como SUM(Aporte) de `raw_ar_event_line`, para Apo = 1.0 UF/cuota exacto), NO
  el VNA contable actual. Apo no tiene bursátil (no transa en bolsa).
- Fondo de amortización consolidada: `CONSOLIDADO_TRI`, `CONSOLIDADO_PT` (fuente: Excel externo
  vía `ingest_financing.py`), `CONSOLIDADO_Apo` (construido en DB sumando `APO_APO_BTG` +
  `APO_APO_EUROAMERICA`, no existe en el Excel fuente).

**Valores validados MAR-26 (bursátil/libro):** A=34.644%/18.038% · C=35.316%/18.065% ·
I=20.184%/18.088% · PT=11.943%/10.313% (=DY normal, sin amortizaciones ese período) ·
Apo=6.307% (capital, sin bursátil).

**Valores validados Apo DIC-25 (capital):** solo BTG=4.364% · BTG+Euroamérica=5.626%
(criterio final: incluir ambos créditos).

**Datos corregidos en `raw_amortizacion` (2026-07-02)**:
- `CONSOLIDADO_TRI`: saldo corregido sumando `TRI_SUCDEN_BICE` (crédito refinanciado ene-2026,
  faltaba en el Excel fuente) — saldo 31-mar-26 ahora exacto (3.532.590 UF). El `capital_uf`
  (flujo) NO se tocó — ya estaba correcto en el Excel fuente tal cual.
- `APO_APO_BTG`: cronograma desde ene-2026 estaba desactualizado (asumía amortización gradual
  hasta oct-2026); corregido con el cronograma real del usuario — el crédito se pagó completo
  en mar-2026 (22.877,79 UF).
- `CONSOLIDADO_Apo`: no existía, creado sumando `APO_APO_BTG` + `APO_APO_EUROAMERICA` (validado
  exacto contra saldo real 2.602.856 UF).

## 5. Fuentes de datos

| Dato | Tabla | Campo clave |
|------|-------|-------------|
| VNA contable / bursátil | `raw_valor_cuota_line` | `precio_uf`, `tipo` |
| Aportes / Disminuciones | `raw_ar_event_line` | `monto_uf`, `cuotas`, `detalle` |
| Dividendos | `raw_dividendo_line` | `monto_uf_cuota`, `fecha_pago`, `tipo`, `superseded_at` |
| UF diaria | `fact_uf` | `valor` |

---

## 6. Implementación — script `scripts/_compute_kpis_mar26.py`

Funciones validadas:
- `xirr(cashflows)` — bisección, convergencia 3000 iter, tolerancia 1e-10
- `get_vc(cur, nemo, fecha, tipo)` — ORDER BY fecha DESC LIMIT 1
- `dividendos_serie(cur, nemo, desde, hasta)` — filtros wiki completos
- `tir_por_cuota(cur, nemo, cuotas_totales, fecha_corte, tipo)` — TRI
- `tir_simple_uf(cur, nemo, fecha_corte, tipo)` — PT/APO
- `ret_acumulado(vc_ini, vc_fin, divs)` — YTD simple

DB activa: `memory/agente_toesca_v2.db`
