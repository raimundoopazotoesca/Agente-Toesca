-- Migration 035: agregar uf_dia y precio_uf a raw_valor_cuota_bursatil_line
-- Backfill con UF mensual de raw_valor_cuota_line (mejor aproximación disponible)
-- Para precisión diaria: ingestar raw_uf_diaria_line desde Banco Central (tarea futura)

ALTER TABLE raw_valor_cuota_bursatil_line ADD COLUMN uf_dia   REAL;
ALTER TABLE raw_valor_cuota_bursatil_line ADD COLUMN precio_uf REAL;

UPDATE raw_valor_cuota_bursatil_line
SET uf_dia = (
    SELECT uf_dia FROM raw_valor_cuota_line
    WHERE uf_dia IS NOT NULL AND fecha <= raw_valor_cuota_bursatil_line.fecha
    ORDER BY fecha DESC LIMIT 1
);

UPDATE raw_valor_cuota_bursatil_line
SET precio_uf = CASE WHEN uf_dia IS NOT NULL THEN precio_clp / uf_dia ELSE NULL END;
