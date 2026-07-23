-- Ocupación diaria/mensual del parking Parque Titanium (SABA).
-- Ver conversación 2026-07-23: tarifa 40 CLP/min y 502 estacionamientos
-- totales son constantes fijas (no viven en tabla, se hardcodean aquí).
--
-- tiempo_promedio_ticket_min = (bruto_dia/tickets_dia) / 40
-- tiempo_total_dia_min       = tiempo_promedio_ticket_min * tickets_dia = bruto_dia/40
-- estacionamientos_no_abonados = (ingresos_variables_u12m / ingresos_totales_u12m) * 502
--   ingresos_variables = todo concepto tipo='venta' excepto el codigo de Abonados
--   (u12m = últimos 12 periodos con datos, ratio fijo, no rolling por ahora)
-- tiempo_disponible_dia_min  = 8*60*estacionamientos_no_abonados
-- ocupacion_diaria           = tiempo_total_dia_min / tiempo_disponible_dia_min
-- ocupacion_mensual          = sum(tiempo_total_dia_min) / sum(tiempo_disponible_dia_min)
--   (equivale al promedio simple de ocupacion_diaria mientras el denominador
--    diario sea constante dentro del mes)

CREATE VIEW v_parking_ratio_no_abonados AS
WITH ult12 AS (
  SELECT DISTINCT periodo FROM raw_parking_ingreso_line
  WHERE activo_key = 'Parking PT'
  ORDER BY periodo DESC LIMIT 12
),
tot AS (
  SELECT
    SUM(CASE WHEN c.codigo != '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_variables_u12m,
    SUM(i.monto_clp) AS ingresos_totales_u12m
  FROM raw_parking_ingreso_line i
  JOIN dim_concepto_parking c ON c.id = i.concepto_id
  WHERE i.activo_key = 'Parking PT' AND i.superseded_at IS NULL
    AND i.periodo IN (SELECT periodo FROM ult12)
)
SELECT
  ingresos_variables_u12m,
  ingresos_totales_u12m,
  CAST(ingresos_variables_u12m AS REAL) / ingresos_totales_u12m AS ratio_variable,
  (CAST(ingresos_variables_u12m AS REAL) / ingresos_totales_u12m) * 502 AS estacionamientos_no_abonados
FROM tot;

CREATE VIEW v_parking_ocupacion_diaria AS
SELECT
  t.activo_key,
  t.fecha,
  substr(t.fecha, 1, 7) AS periodo,
  t.tickets,
  t.feriado,
  t.monto_bruto_clp,
  r.estacionamientos_no_abonados,
  t.monto_bruto_clp / 40.0 AS tiempo_total_min,
  8 * 60 * r.estacionamientos_no_abonados AS tiempo_disponible_min,
  (t.monto_bruto_clp / 40.0) / (8 * 60 * r.estacionamientos_no_abonados) AS ocupacion_diaria
FROM raw_parking_ticket_line t
CROSS JOIN v_parking_ratio_no_abonados r
WHERE t.superseded_at IS NULL;

CREATE VIEW v_parking_ocupacion_mensual AS
SELECT
  activo_key,
  periodo,
  COUNT(*) AS dias,
  SUM(tickets) AS tickets_mes,
  SUM(monto_bruto_clp) AS bruto_mes,
  SUM(tiempo_total_min) AS tiempo_total_min_mes,
  SUM(tiempo_disponible_min) AS tiempo_disponible_min_mes,
  SUM(tiempo_total_min) / SUM(tiempo_disponible_min) AS ocupacion_mensual
FROM v_parking_ocupacion_diaria
GROUP BY activo_key, periodo;
