# TIR desde Inicio — Metodología canónica (todos los fondos)

> Documento de referencia. Cualquier agente que calcule TIR desde inicio DEBE seguir esta metodología
> y usar estas fuentes de datos. No inventar variantes.

---

## TRI series (A / C / I) — método `tir_por_cuota`

Se usa cuando hay aportes posteriores al primer VNA contable (fondos con múltiples rondas).

### Fuentes de datos

| Dato | Tabla | Campo |
|---|---|---|
| Aportes y Disminuciones | `raw_ar_event_line` | `monto_uf`, `cuotas`, `fecha` |
| Dividendos | `raw_dividendo_line` | `monto_uf_cuota`, `fecha_pago` |
| Terminal VNA contable | `raw_valor_cuota_line` | `precio_uf` donde `tipo='contable'` |
| Terminal VNA bursatil | `raw_valor_cuota_line` | `precio_uf` donde `tipo='bursatil'` |

### Paso 1 — Cuotas totales de aportes (divisor fijo por serie)

```sql
cuotas_totales = SUM(cuotas)
FROM raw_ar_event_line
WHERE nemotecnico = <serie> AND detalle = 'Aporte'
```

| Serie | cuotas_totales_aporte |
|---|---|
| CFITOERI1A | 526,079 |
| CFITOERI1C | 1,385,310 |
| CFITOERI1I | 908,887 |

### Paso 2 — Terminal VNA

```sql
terminal = precio_uf
FROM raw_valor_cuota_line
WHERE nemotecnico = <serie>
  AND tipo = 'contable'   -- o 'bursatil' para tir_bursatil
  AND fecha <= FECHA_CORTE
ORDER BY fecha DESC LIMIT 1
```

**IMPORTANTE**: el terminal siempre viene de `raw_valor_cuota_line`. NUNCA de `raw_ar_event_line`
(los VR de raw_ar_event_line pueden estar desactualizados respecto a los EEFF publicados).

### Paso 3 — Construir flujos (en UF/cuota)

| Fuente | detalle | flujo UF/cuota | fecha |
|---|---|---|---|
| `raw_ar_event_line` | `Aporte` | `-(monto_uf / cuotas_totales)` | fecha real del aporte |
| `raw_ar_event_line` | `Disminucion` | `+(monto_uf / cuotas_row)` | fecha real |
| `raw_dividendo_line` | — | `+monto_uf_cuota` | `fecha_pago` real |
| terminal (VNA) | — | `+precio_uf` | FECHA_CORTE |
| `raw_ar_event_line` | `Canje Cuotas` | **EXCLUIR** | — |
| `raw_ar_event_line` | `VR Contable/Bursatil` | **EXCLUIR** | — |

Filtros raw_dividendo_line:
- `superseded_at IS NULL`
- `tipo = 'dividendo'`
- `monto_uf_cuota IS NOT NULL AND monto_uf_cuota > 0`
- `fecha_pago <= FECHA_CORTE`

### Paso 4 — XIRR

Ordenar todos los flujos por fecha. Usar bisección:

```
0 = Σ CF_i / (1 + r)^((d_i - d_0) / 365)
```

- `d_0` = fecha del primer flujo (primer aporte)
- `d_i` = fecha real de cada flujo
- **No agrupar por año, no mover fechas al cierre del período**

---

## PT (serie única CFITRIPT-E) — método `tir_simple_uf`

Se usa cuando no hay aportes posteriores al primer VNA (fondo con aporte único de lanzamiento).

1. `T0` = fecha del primer registro en `raw_valor_cuota_line` tipo=`contable`
2. Flow en T0 = `−precio_uf` del primer VNA (precio implícito de la inversión)
3. Dividendos = `+monto_uf_cuota` de `raw_dividendo_line`, fechas reales
4. Terminal = `precio_uf` de `raw_valor_cuota_line` al FECHA_CORTE
5. XIRR idéntico

Para bursatil PT: terminal desde `fact_precio_cuota` / `fact_uf` (no hay bursatil en raw_valor_cuota_line para PT).

---

## Valores de referencia validados (dic-2025)

| Serie | TIR contable desde inicio | TIR bursatil desde inicio |
|---|---|---|
| CFITOERI1A | **0.301%** | -8.19% |
| CFITOERI1C | **0.855%** | -6.47% |
| CFITOERI1I | **0.957%** | -0.13% |
| CFITRIPT-E | **-5.28%** | -6.42% |

Confirmados contra CDG manual del usuario (jun-2025).

---

## TIR BURSÁTIL desde inicio — método agregado (CONGELADO, validado exacto 2026-07)

> **NUNCA CAMBIAR.** Reconstruye byte a byte la fórmula real de Excel del usuario
> (`TIR.NO.PER(Tabla1[Bolsa Inicio <serie>]; Tabla1[Fecha])`, confirmada contra su
> planilla `tablaflujos.xlsx`, corte MAR-2026). Es un método **distinto** al contable:
> opera en UF **agregadas** de la serie (no UF/cuota, no divisor fijo).

```
Aporte        → -monto_uf                                (raw_ar_event_line)
Disminucion   → +monto_uf                                (raw_ar_event_line)
Canje Cuotas  → -monto_uf   (monto_uf puede ser + o -)    (raw_ar_event_line)
Dividendo     → +monto_uf_cuota × cuotas_en_circulacion   (raw_dividendo_line × raw_cuota_en_circulacion)
Terminal      → +precio_uf_bursatil(fecha_corte EXACTA) × cuotas_en_circulacion
```

- `cuotas_en_circulacion(fecha)` = snapshot más reciente `<= fecha` en `raw_cuota_en_circulacion` (fuente EEFF).
- El precio bursátil terminal exige **fecha exacta** de corte en `raw_valor_cuota_line` (no "más reciente ≤"; así es la fórmula original — si no hay fila exacta, el KPI no se calcula para ese corte).
- Implementación: `_calcular_tir_bursatil_agregado` en `tir.py`.

**Valores validados MAR-26:** A=-7.234% · C=-6.111% · I=-0.733%
(I corregido: la planilla del usuario omite un dividendo real del 29-dic-2021 en
la columna `Bolsa Inicio I2` — mismo patrón de bug que el ya documentado en TIR U12M
serie I. Se usa el valor correcto, con el dividendo incluido, no el de la planilla.)

**Inputs a futuro** (para actualizar mes a mes, sin la planilla histórica):
UF diaria (API) → `fact_uf` · cuotas en circulación (EEFF) → `raw_cuota_en_circulacion` ·
precio $/cuota (mercado bursátil LarraínValor) → `raw_valor_cuota_line` tipo=`bursatil`.

---

## Implementación en el skill

Archivo: `skills/real-estate-finance-expert/scripts/tir.py`
- Función: `_calcular_tir_por_cuota` → **CONTABLE** TRI y fondos con múltiples aportes (congelado)
- Función: `_calcular_tir_simple_uf` → PT y fondos sin aportes post-VNA (fallback contable)
- Función: `_calcular_tir_bursatil_agregado` → **BURSÁTIL**, todas las series (congelado, ver arriba)
- Dispatch contable: si `COUNT(Aportes WHERE fecha >= primer_VNA) == 0` → usar `tir_simple_uf`

KPI names para llamar el skill:
- `tir_contable_desde_inicio` → `_calcular_tir_por_cuota` / `_calcular_tir_simple_uf`
- `tir_bursatil_desde_inicio` → `_calcular_tir_bursatil_agregado`

Nemotécnicos en la DB: `CFITOERI1A`, `CFITOERI1C`, `CFITOERI1I`, `CFITRIPT-E` (no alias cortos).
