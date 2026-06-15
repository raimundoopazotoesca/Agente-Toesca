-- Migration 029: vistas de compatibilidad para la skill real-estate-finance-expert
-- El skill espera fact_precio_cuota y fact_uf. Esta DB los tiene en tablas distintas.

-- fact_precio_cuota: precios bursátiles en CLP (el skill divide por UF del día)
DROP VIEW IF EXISTS fact_precio_cuota;
CREATE VIEW fact_precio_cuota AS
SELECT
    nemotecnico,
    fecha,
    precio_clp   AS precio,
    fuente
FROM raw_precio_cuota_line;

-- fact_uf: valor UF diario. La DB no tiene tabla UF separada;
-- usamos uf_dia de raw_valor_cuota_line (mensual) como aproximación.
-- Para cálculos diarios el skill usará el último uf_dia conocido <= fecha pedida.
DROP VIEW IF EXISTS fact_uf;
CREATE VIEW fact_uf AS
SELECT DISTINCT
    fecha,
    uf_dia  AS valor
FROM raw_valor_cuota_line
WHERE uf_dia IS NOT NULL
ORDER BY fecha;
