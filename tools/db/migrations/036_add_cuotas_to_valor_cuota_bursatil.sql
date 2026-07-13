-- Migration 036: agregar n_cuotas y patrimonio_bursatil_uf a raw_valor_cuota_bursatil_line
-- n_cuotas: último valor conocido de raw_cuota_en_circulacion_line con fecha <= precio
-- patrimonio_bursatil_uf: precio_uf * n_cuotas

ALTER TABLE raw_valor_cuota_bursatil_line ADD COLUMN n_cuotas          REAL;
ALTER TABLE raw_valor_cuota_bursatil_line ADD COLUMN patrimonio_bursatil_uf REAL;

UPDATE raw_valor_cuota_bursatil_line
SET n_cuotas = (
    SELECT cuotas FROM raw_cuota_en_circulacion_line c
    WHERE c.nemotecnico = raw_valor_cuota_bursatil_line.nemotecnico
      AND c.fecha <= raw_valor_cuota_bursatil_line.fecha
    ORDER BY c.fecha DESC LIMIT 1
);

UPDATE raw_valor_cuota_bursatil_line
SET patrimonio_bursatil_uf = CASE
    WHEN precio_uf IS NOT NULL AND n_cuotas IS NOT NULL
    THEN precio_uf * n_cuotas
    ELSE NULL
END;
