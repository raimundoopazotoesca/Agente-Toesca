-- Migration 034: rename raw_precio_cuota_line → raw_valor_cuota_bursatil_line
-- Reason: symmetric with raw_valor_cuota_line; "bursatil" vs (implied) "contable/libro"

ALTER TABLE raw_precio_cuota_line RENAME TO raw_valor_cuota_bursatil_line;
DROP INDEX IF EXISTS idx_raw_precio_nemo_fecha;
CREATE INDEX idx_raw_valor_cuota_bursatil_nemo_fecha ON raw_valor_cuota_bursatil_line(nemotecnico, fecha);

-- Update compat view
DROP VIEW IF EXISTS fact_precio_cuota;
CREATE VIEW fact_precio_cuota AS
SELECT
    nemotecnico,
    fecha,
    precio_clp   AS precio,
    fuente
FROM raw_valor_cuota_bursatil_line;
