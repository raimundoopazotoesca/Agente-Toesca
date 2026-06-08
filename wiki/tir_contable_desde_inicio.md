# TIR Contable desde Inicio — Metodología

## Fuentes de datos

- `raw_ar_event_line` — eventos A&R del CDG por fondo/serie (aportes, dividendos, disminuciones)
- `raw_valor_cuota_line` — precios UF/cuota contable (fuente del terminal VR)

## Paso 1 — Cuotas totales de aportes (divisor fijo por serie)

```sql
cuotas_totales_serie = SUM(cuotas)
WHERE detalle = 'Aporte'
  AND nemotecnico = <serie>
```

Valores conocidos:
| Serie | cuotas_totales_aporte |
|---|---|
| CFITOERI1A | 526,079 |
| CFITOERI1C | 1,385,310 |
| CFITOERI1I | 908,887 |

## Paso 2 — Terminal VR Contable

```sql
terminal = precio_uf
FROM raw_valor_cuota_line
WHERE nemotecnico = <serie> AND tipo = 'contable' AND fecha <= FECHA_CORTE
ORDER BY fecha DESC LIMIT 1
```

El terminal NO proviene de los VR rows de `raw_ar_event_line`.

## Paso 3 — Construir flujos XIRR

Para cada fila de `raw_ar_event_line` ordenada por `fecha ASC`:

| detalle | flujo | condición |
|---|---|---|
| `Aporte` | `-(monto_uf / cuotas_totales_serie)` | siempre |
| `Dividendo` | `+(monto_uf / cuotas_row)` | solo si `fecha <= FECHA_CORTE` |
| `Disminucion` | `+(monto_uf / cuotas_row)` | solo si `fecha <= FECHA_CORTE` |
| `VR Contable` | excluir | — |
| `VR Bursatil` | excluir | — |
| `Canje Cuotas` | excluir | flujo = 0 |

Agregar como último flujo: `(terminal_per_cuota, FECHA_CORTE)`.

> **Nota clave**: aportes usan `cuotas_totales_serie` (total histórico de aportes) como denominador.
> Dividendos/disminuciones usan `cuotas_row` (cuotas outstanding en esa fila específica).

## Paso 4 — XIRR

```python
tir = xirr(cashflows, dates)  # tasa anual como ratio
```

## Diferencias respecto a otras TIR

| KPI | Fuente terminal | Denominador aportes | Ventana |
|---|---|---|---|
| `tir_contable_desde_inicio` | `raw_valor_cuota_line` tipo=contable | cuotas totales de aportes | desde primer aporte |
| `tir_bursatil_desde_inicio` | `raw_valor_cuota_line` tipo=bursatil | cuotas totales de aportes | desde primer aporte |
| `tir_contable_ytd` | `raw_valor_cuota_line` precio inicial/final | N/A (método precio) | 31-dic año anterior → hoy |
| `tir_contable_u12m` | `raw_valor_cuota_line` precio inicial/final | N/A (método precio) | hace 12 meses → hoy |

## Valores de referencia (dic-2025)

| Serie | TIR contable desde inicio | Fuente |
|---|---|---|
| CFITOERI1A | ~0.18% | CDG Excel "Cálculo TIRcontable..." |
| CFITOERI1C | ~0.73% | CDG Excel |
| CFITOERI1I | ~0.82% | CDG Excel |

> La DB produce ~0.30% / 0.86% / 0.96% — diferencia <0.15% por cuotas outstanding
> ligeramente distintas entre CDG (457,667 para A) y DB (475,667 para A).

## Referencia

Archivo CDG: `work/Cálculo TIRcontable desde el inicio - Fondo Rentas.xlsx`
Celda resultado: AB3 de cada hoja (A, C, I).
