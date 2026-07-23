-- Resultados de Parking PT en UF. Ver conversación 2026-07-23.
--
-- ingresos_netos = total ingresos mensual (suma tipo='venta') = fila 13 de la
--   planilla = fila 33 "liquidacion factura-Neto" (mismo valor, verificado
--   exacto contra 2026-06: 118.861.096 en ambos)
-- gastos_netos   = total gastos mensual (suma tipo='gasto') = fila 27 = fila
--   29 "facturacion SABA-Neto" (mismo valor, verificado exacto: 16.030.297)
-- resultado_neto_uf     = (ingresos_netos - gastos_netos) / UF
-- ingresos_variables_uf = ingresos_variables / UF  (variables = todo 'venta'
--   excepto codigo 70500003-250 = Abonados)
-- ingresos_abonados_uf  = ingresos_abonados / UF   (codigo 70500003-250)
-- UF del periodo = valor de raw_uf_diaria del último día con dato del mes.

CREATE VIEW v_parking_resultado_uf AS
WITH mensual AS (
  SELECT
    i.periodo,
    SUM(i.monto_clp) AS ingresos_netos_clp,
    SUM(CASE WHEN c.codigo != '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_variables_clp,
    SUM(CASE WHEN c.codigo = '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_abonados_clp
  FROM raw_parking_ingreso_line i
  JOIN dim_concepto_parking c ON c.id = i.concepto_id
  WHERE i.activo_key = 'Parking PT' AND i.superseded_at IS NULL
  GROUP BY i.periodo
),
gastos AS (
  SELECT periodo, SUM(monto_clp) AS gastos_netos_clp
  FROM raw_parking_gasto_line
  WHERE activo_key = 'Parking PT' AND superseded_at IS NULL
  GROUP BY periodo
),
uf_ult_dia AS (
  SELECT substr(fecha, 1, 7) AS periodo, MAX(fecha) AS last_fecha
  FROM raw_uf_diaria
  GROUP BY substr(fecha, 1, 7)
),
uf_mes AS (
  SELECT ud.periodo, u.valor AS uf_valor
  FROM uf_ult_dia ud
  JOIN raw_uf_diaria u ON u.fecha = ud.last_fecha
)
SELECT
  m.periodo,
  m.ingresos_netos_clp,
  g.gastos_netos_clp,
  m.ingresos_netos_clp - g.gastos_netos_clp AS resultado_neto_clp,
  u.uf_valor,
  (m.ingresos_netos_clp - g.gastos_netos_clp) / u.uf_valor AS resultado_neto_uf,
  m.ingresos_variables_clp / u.uf_valor AS ingresos_variables_uf,
  m.ingresos_abonados_clp / u.uf_valor AS ingresos_abonados_uf
FROM mensual m
JOIN gastos g ON g.periodo = m.periodo
JOIN uf_mes u ON u.periodo = m.periodo;
