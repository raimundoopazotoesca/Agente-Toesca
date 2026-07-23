# Parking PT (SABA)

Activo `Parking PT` en `dim_activo` (fondo_key `PT`), agregado en migración 053. Representa el
parking del complejo Parque Titanium completo (no una torre específica), operado por SABA.

## Tablas

- `dim_concepto_parking` — catálogo de conceptos de ingreso/gasto (código, nombre, tipo, signo)
- `raw_parking_ingreso_line` / `raw_parking_gasto_line` — mensual, por concepto
- `raw_parking_ticket_line` — diario: `tickets`, `feriado`, `monto_bruto_clp` (col H "Total Bruto"
  de la planilla, agregada en migración 054)
- `raw_parking_facturacion_line` — mensual: neto/iva/bruto SABA y liquidación, `pago_a_pt`

Fuente: `RAW/Parking PT DB.xlsx` (hojas Ingresos + Tickets), ingesta one-shot vía
`scripts/ingest_parking_pt_historico.py` (no reusable, rangos de filas hardcodeados contra esa
planilla puntual).

## Ocupación (migración 055)

Metodología acordada con el usuario 2026-07-23:

- **Ingresos variables** = todo concepto `tipo='venta'` excepto el código `70500003-250`
  (Abonados (Neto) + sus notas de crédito)
- **Estacionamientos no abonados** = `(ingresos_variables_u12m / ingresos_totales_u12m) × 502`
  — 502 = total de estacionamientos del complejo, constante fija. El ratio U12M es fijo (últimos
  12 periodos con datos), no rolling por mes — a revisar si el criterio cambia más adelante.
- **Tiempo total del día (min)** = `bruto_día / 40` (simplifica de
  `(bruto/tickets)/40 tarifa-min × tickets`; 40 = tarifa CLP/minuto SABA)
- **Tiempo disponible del día (min)** = `8h × 60 × estacionamientos_no_abonados`
- **Ocupación diaria** = tiempo_total / tiempo_disponible
- **Ocupación mensual** = `sum(tiempo_total_día) / sum(tiempo_disponible_día)` del mes — equivale
  al promedio simple de las diarias mientras el denominador diario sea constante en el mes (lo es,
  dado que 502, 8h y el ratio U12M no cambian intra-mes)

Vistas: `v_parking_ratio_no_abonados` (1 fila, ratio+estacionamientos), `v_parking_ocupacion_diaria`,
`v_parking_ocupacion_mensual`.

Valores de referencia (2026-06): ratio variable ≈0.60, estacionamientos no abonados ≈301,
ocupación mensual ≈0.48.
