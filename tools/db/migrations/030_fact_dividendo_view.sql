-- Migration 030: fact_dividendo view en CLP (consistente con fact_precio_cuota)
-- fact_dividendo.monto = CLP por cuota (para usar con rentabilidades en CLP)
-- fact_dividendo.monto_uf = UF por cuota (para dividend_yield)

DROP VIEW IF EXISTS fact_dividendo;
CREATE VIEW fact_dividendo AS
SELECT
    nemotecnico,
    fecha_pago,
    monto_clp_cuota  AS monto,
    monto_uf_cuota   AS monto_uf,
    periodo,
    fondo_key
FROM raw_dividendo_line
WHERE superseded_at IS NULL
  AND tipo = 'dividendo';
