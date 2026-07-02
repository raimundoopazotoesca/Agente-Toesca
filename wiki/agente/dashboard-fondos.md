# Dashboard Fondos — fact sheets dinámicos

**Archivo:** `dashboards/fondos.py` · **Run:** `python -m streamlit run dashboards/fondos.py`

Página estilo dashboard de los 3 fondos (TRI, PT, Apo) con estética Toesca
(banda negra, wordmark serif `toesca.`, banners de sección verde menta, paleta
categórica validada con verde `#149E63` como primario). Objetivo de largo plazo:
reemplazar los fact sheets PDF por fact sheets dinámicos alimentados por la DB.

## Vistas

- **Portfolio**: cards patrimonio/deuda por fondo, tabla comparativa de
  rentabilidad por serie, evolución TIR bursátil desde inicio, NOI del
  portfolio por categoría.
- **TRI / PT / Apo** (fact sheet dinámico): réplica de los bloques del FS PDF:
  1. KPI cards: patrimonio contable, valor cuota libro, deuda financiera, tasa promedio, LTV, leverage
  2. Rentabilidad del fondo (desde inicio / YTD / U12M / DY / DY+amort × bursátil/libro por serie)
  3. Valor cuota (evolución libro y bursátil)
  4. Repartos últimos 12 meses
  5. Endeudamiento (evolución deuda UF, perfil de vencimiento, detalle por crédito)
  6. NOI mensual por activo (UF, 100% del activo)
  7. Vacancia desde rent roll
  8. Tasaciones y LTV por activo
  9. Ficha estática del fondo (fechas, duración, remuneraciones — hardcodeado en `FICHA`)

## Fuentes de datos (todas `memory/agente_toesca_v2.db`)

| Bloque | Fuente |
|---|---|
| Rentabilidades / DY | `derived_kpi` (tir_*, rent_ytd_*, dy, dy_amort) — valores congelados/validados vs CDG |
| Valor cuota | `raw_valor_cuota_contable` / `raw_valor_cuota_bursatil` (`precio_clp`; bursátil NO tiene `superseded_at`) |
| Patrimonio / cuotas | `v_serie_patrimonio` (último período) |
| Repartos | `raw_dividendo` dedup con `GROUP BY fecha_pago,tipo,serie → MAX(monto)` (hay filas duplicadas por doble fuente) |
| Deuda | `raw_saldo_deuda` (último período ≤ hoy por crédito) + `dim_credito` (tasa, vencimiento) |
| Tasaciones | `fact_tasacion` — usar fila `tasador='Promedio'` si existe, si no AVG de tasadores |
| NOI | `derived_kpi` kpi='noi_mensual' (keys propias: 'PT Torre A', 'PT Boulevard', 'Apoquindo', etc. — mapa `NOI_ACTIVOS`) |
| Vacancia | `raw_rent_roll_line`: vacante = `arrendatario LIKE 'Vacante%'` (¡renta_uf es UF/m² pedido, no ocupación!) |

## Detalles aprendidos

- `Apo` no transa en bolsa (`dim_serie.transa_bolsa=0`) → solo columnas Libro; su
  `dy_amort` se guarda con `variante='capital'` (no 'contable').
- Tasaciones de residencias INMOSA 2025 vienen con `valor_uf=0` → filtrar `>0`
  (caen al último período con valor).
- Deuda TRI directa (10 créditos ≈ UF 2,43M) ≠ deuda consolidada del FS
  (UF 3,7M incluye proporción PT/Apo) — pendiente consolidación para réplica exacta.
- Los bloques se ocultan solos si su query vuelve vacía → al poblar la DB aparecen
  sin tocar código.

## Pendiente para réplica completa del FS

- Balance consolidado (desde `raw_eeff_line` ESF con subtotales)
- Ingresos U12M / tasa arriendo / cap rate (requiere más EERR por activo)
- Performance activos (m², renta vacante, absorción — requiere rent roll histórico completo)
- Composición por rubro de arrendatario (requiere campo rubro en rent roll)
- Deuda consolidada TRI (proporción PT/Apo)
