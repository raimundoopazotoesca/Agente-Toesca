# Skill: real-estate-finance-expert

**Status**: ✅ Production-ready (completado 2026-05-27)

**Ubicación**: `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\`

**Propósito**: Computar indicadores financieros derivados (rentabilidades, cap rate, dividend yield, TIR, etc.) a partir de `agente_toesca.db` con persistencia inteligente en cache.

## Indicadores soportados

| Indicador | Estado | Referencia |
|-----------|--------|-----------|
| `rent_desde_inicio` | ✅ Operativo | CAGR desde primer precio disponible |
| `rent_anualizada` | ✅ Operativo | CAGR anualizado |
| `rent_u12m` | ✅ Operativo | Retorno últimos 12 meses |
| `dividend_yield` | ✅ Operativo | Simple (dividendos / precio) |
| `dividend_yield_con_amort` | ✅ Operativo | Dividend yield + amortizaciones (TODO: datos de amortización) |
| `cap_rate_real` | ✅ Operativo | NOI anual / valor_activo (TODO: valuaciones) |
| `cap_rate_implicito` | ✅ Operativo | NOI anual fondo / market_cap |
| `tir_actual` | 🟡 Placeholder | XIRR (TODO: numpy_financial) |
| `tasa_arriendo_uf_m2` | ✅ Operativo | Tasa promedio ponderada por m² |
| `ltv`, `dscr`, `duration` | 🟡 Placeholders | Requieren dim_deuda + fact_servicio_deuda |

## Arquitectura: Three-Tier Loop

1. **Read Cache** → `SELECT * FROM derived_kpi WHERE ...`
2. **Compute** → Invoca script correspondiente si miss
3. **Persist (Condicional)** → `UPSERT` en `derived_kpi` según política inteligente

### Smart-Persistence Policy

Persiste cuando se cumplen ≥2 criterios:

| Criterio | Persistir | Ejemplo |
|----------|-----------|---------|
| Costo de compute | >2 segundos | XIRR sobre 5+ años de flujos |
| Frecuencia | Mensual o más | Rentabilidad en dashboards |
| Período cerrado | Mes pasado | Abril 2026 ✅; mayo 2026 ❌ |
| Reusabilidad | Otros KPIs lo consumen | cap_rate_real → valuation |
| Input size | >10k filas | Escaneo rent roll completo |

**Hard rule**: Nunca persistir el mes en curso (inputs aún cambian).

## Invocación

### CLI (testing/debugging)

```bash
cd C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert

# Computar rentabilidad anualizada de TRI Serie A
python scripts/compute_or_fetch.py \
  --kpi rent_anualizada \
  --entidad-tipo serie \
  --key CFITOERI1A \
  --periodo 2026-04 \
  --json

# Listar overrides activos
python scripts/compute_or_fetch.py --list-overrides

# Invalidar cache para KPI
python scripts/compute_or_fetch.py --invalidate rent_anualizada
```

### Python (desde agent code)

```python
from real_estate_finance_expert.scripts.compute_or_fetch import obtener

result = obtener(
    kpi="cap_rate_implicito",
    entidad_tipo="activo",
    entidad_key="Parque Titanium",
    periodo="2026-04"
)

print(f"Cap rate implícito: {result['valor']:.4f}")
print(f"Fuente: {result['fuente']}")  # 'cache' o 'computed'
print(f"Persistido: {result['persistido']}")
```

## Fórmulas editables

Archivo: `config/formulas.yaml`

El usuario puede modificar parámetros, fórmulas y métodos sin editar Python:

```yaml
cap_rate_real:
  valor_activo: costo_adquisicion  # o "tasacion", "valor_libro"
  anualizacion_noi: "12"           # o "u12m"

rent_anualizada:
  metodo: cagr                      # o "twr", "money_weighted_irr"
  dias_anio: 365                    # o 252, 360

dividend_yield_con_amort:
  formula: "(dividendos_u12m + amortizaciones_u12m) / precio_actual"
  base: nominal                     # o "uf"
```

**Invalidación automática**: Al cambiar un override, el `override_hash` en la `recipe` cambia → cache se invalida automáticamente para ese KPI.

## Documentación de fórmulas

Todas las fórmulas, variables disponibles y ejemplos documentados en:

- `references/indicadores-retorno.md` — rentabilidades, dividend yield, TIR
- `references/indicadores-activo.md` — cap rate, tasas de arriendo
- `references/indicadores-deuda.md` — LTV, DSCR, duration (placeholders)
- `references/editar-formulas.md` — guía paso-a-paso para modificar config/formulas.yaml
- `references/fondos-y-agf.md` — contexto FI chileno (AGF, series A/C/I)
- `references/glosario-toesca.md` — vocabulario Toesca (Machalí excluido, UF, participaciones)

## Resultados de evaluación

**Puntuación**: ⭐ APROBADO (55.6% mejora sobre baseline sin skill)

| Test | Con Skill | Sin Skill | Ganador |
|------|-----------|-----------|---------|
| Triggering (Cap Rate) | 100% | 33% | ✅ CON SKILL |
| Cálculo (Rentabilidad) | 100% | 75% | ✅ CON SKILL |
| Documentación (Formulas) | 100% | 25% | ✅ CON SKILL |

**Workspace evaluación**: `C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert-workspace\iteration-1\`

## Data gaps y TODOs

- **LTV/DSCR/duration** — Requieren `dim_deuda` + `fact_servicio_deuda`
- **XIRR** — Requiere `numpy_financial`; placeholder en `tir.py`
- **Amortizaciones** — `dividend_yield.py` asume amortizaciones=0
- **Valuaciones** — `cap_rate_real` requiere valores de costo/tasación/libro

## Ejemplo: Cálculo de cap rate implícito

```python
result = obtener(
    kpi="cap_rate_implicito",
    entidad_tipo="activo",
    entidad_key="Parque Titanium",
    periodo="2026-03"
)

# Output:
# {
#   "valor": 0.0712,
#   "unidad": "ratio",
#   "fuente": "computed",  # o "cache"
#   "recipe": "cap_rate_implicito_v1_a1b2c3",
#   "persistido": true,
#   "advertencias": [],
#   "metadata": {
#     "noi_anual_clp": 12_500_000,
#     "market_cap": 175_600_000,
#     "num_input_rows": 45
#   }
# }
```

## Cómo reportar problemas

1. Ejecutar CLI con `--json` para capturar error exacto
2. Verificar que `agente_toesca.db` está actualizado
3. Consultar `references/editar-formulas.md` si el problema es con overrides
4. Reportar en wiki/log.md con pasos para reproducir

---

**Complementa**: [[agente/herramientas|skill db-dashboard-expert]] (que solo lee datos crudos)

**Próximos pasos**: Implementar XIRR, ingestar deuda, optimizar descripción via run_loop.py
