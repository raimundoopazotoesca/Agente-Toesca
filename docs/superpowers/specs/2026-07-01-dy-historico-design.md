# Spec: Dividend Yield Histórico en derived_kpi

**Fecha**: 2026-07-01
**Alcance**: persistir DY (libro y bursátil) para todas las series de fondos, todos los meses desde inicio, con recipe para cálculo futuro incremental.

---

## Contexto

Los indicadores de Dividend Yield (DY libro y DY bursátil) fueron validados contra el CDG de marzo 2026 y coinciden exactamente (0.00pp de diferencia) para las series TRI A/C/I. Se requiere:
1. Persistirlos históricamente en `derived_kpi`
2. Dejar la fórmula documentada para que el agente los calcule en meses futuros
3. Que el agente sepa que estos KPIs ya están validados y debe leerlos del cache primero

---

## Fórmula Canónica Validada

```
DY = sum(monto_clp_cuota con fecha_pago ∈ [t-12m, t]) / precio_clp(t)
```

- Se trabaja en CLP (el UF se cancela: divs_clp / precio_clp = divs_uf / precio_uf)
- `t` = último día del mes calendario
- Ventana: 12 meses móviles hacia atrás desde t
- Precio: último precio disponible con fecha <= t

**Validado**: DY libro y DY bursátil coinciden exacto con CDG MAR-2026 para TRI A/C/I.

---

## Schema: Migración 033

Agregar columna `variante` a `derived_kpi` para separar contable/bursátil del mismo KPI:

```sql
-- tools/db/migrations/033_add_variante_derived_kpi.sql
ALTER TABLE derived_kpi ADD COLUMN variante TEXT DEFAULT NULL;
```

**Convención de valores**:
- `variante = 'contable'` — basado en precio libro (valor NAV)
- `variante = 'bursatil'` — basado en precio de mercado
- `variante = NULL` — KPIs que no tienen esta distinción (NOI, vacancia, etc.)

La clave única efectiva pasa a ser: `(entidad_tipo, entidad_key, periodo, kpi, variante)`.

---

## Script: `scripts/compute_kpis_series.py`

### Modo de uso

```bash
# Backfill histórico completo
python scripts/compute_kpis_series.py --kpi dy --modo backfill

# Incremental (mes actual por defecto)
python scripts/compute_kpis_series.py --kpi dy

# Rango específico
python scripts/compute_kpis_series.py --kpi dy --desde 2024-01 --hasta 2026-03
```

### Series a procesar

| Nemotecnico | Fondo | DY contable | DY bursatil | Desde |
|---|---|---|---|---|
| CFITOERI1A | TRI Serie A | ✅ | ✅ | 2018-03 |
| CFITOERI1C | TRI Serie C | ✅ | ✅ | 2018-03 |
| CFITOERI1I | TRI Serie I | ✅ | ✅ | 2018-03 |
| CFITRIPT-E | PT | ✅ | ✅ | 2018-03 |
| Apo | Apoquindo | ✅ | ❌ (no transa bolsa) | 2019-03 |

### Fuentes de precio por tipo

**Precio bursátil** (jerarquía fija, permanente):
1. `raw_valor_cuota_bursatil_line` (LarrainVial) — fuente primaria para todo período
2. `raw_valor_cuota_contable_line` tipo='bursatil' — fallback solo para meses anteriores a 2024-05 donde LarrainVial no tiene dato

**Precio contable**:
- `raw_valor_cuota_contable_line` tipo='contable' — última fecha disponible con fecha <= t
- Step function: meses entre EEFF trimestrales usan el precio del trimestre anterior

### Lógica de persistencia en derived_kpi

```python
# Para cada serie, para cada mes t desde inicio hasta hoy:
upsert derived_kpi SET
  entidad_tipo = 'serie',
  entidad_key  = nemotecnico,
  periodo      = 'YYYY-MM',
  kpi          = 'dy',
  variante     = 'contable' | 'bursatil',
  valor        = dy_calculado,
  unidad       = 'ratio',
  recipe       = 'dy_v1',
  computed_at  = now()
```

**Recipe `dy_v1`**: identifica la fórmula actual. Si cambia la fórmula, incrementar a `dy_v2` → el three-tier loop recomputa automáticamente.

---

## Regla de Fuente Bursátil (permanente)

> **Los precios bursátiles de fondos Toesca siempre vienen de LarrainVial (`raw_valor_cuota_bursatil_line`).** Los valores en `raw_valor_cuota_contable_line` tipo='bursatil' son datos históricos del CDG/EEFF que se usan como fallback para períodos sin cobertura de LarrainVial.

Esta regla aplica a DY, CAGR, U12M, YTD y cualquier indicador futuro que use precio bursátil.

---

## Actualizaciones al Skill real-estate-finance-expert

Agregar al Indicator Map del skill:

```
| dy | indicadores-retorno | compute_kpis_series.py | divs, precio | Sí — validado vs CDG |
```

Agregar nota en la sección de cache:
- `dy` con recipe `dy_v1` está validado contra CDG MAR-2026
- Leer siempre de `derived_kpi` primero antes de computar

---

## Cobertura Histórica Esperada

- **DY contable TRI/PT**: desde 2018-03 (step trimestral, mensual a partir de cuando tengamos precios mensuales)
- **DY bursátil TRI**: desde 2017-12 (fallback a raw_valor_cuota_contable_line), mensual desde 2024-05 (LarrainVial)
- **DY bursátil PT**: desde 2017-11 (LarrainVial tiene 122 meses)
- **DY Apo**: solo contable desde 2019-03; último dividendo oct-2022, DY=0% desde entonces

---

## Fuera de Alcance (este spec)

- CAGR desde inicio (gaps pendientes de resolver)
- U12M (gaps pendientes)
- YTD (pendiente ajuste menor)
- DY + Amortización (falta ingesta de datos de amortización)

Estos se abordan en specs separados una vez que se identifique la fórmula exacta del CDG.
