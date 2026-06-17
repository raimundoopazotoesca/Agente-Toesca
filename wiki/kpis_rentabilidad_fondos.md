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

## 2. Rentabilidad YTD acumulada

```
YTD = (VNA_corte + sum(dividendos_periodo)) / VNA_inicio_año - 1
```

- `VNA_inicio_año` = VNA contable al 31-DIC del año anterior
- `dividendos_periodo` = dividendos con fecha_pago ≥ 01-ENE-año AND ≤ fecha_corte
- **No anualizar** (el CDG la llama "anualizada" en el header pero es retorno acumulado simple)
- Para corte MAR-26: no hubo dividendos Q1-2026 → YTD = puro cambio de VNA

**Valores validados MAR-26 (libro):** A=1.192% · C=1.238% · I=1.257%

Nota: CDG muestra A=1.209% / C=1.255% / I=1.274%. Delta ~0.017pp sin explicación
con entradas idénticas — ruido de planilla, no ajustar la metodología.

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
