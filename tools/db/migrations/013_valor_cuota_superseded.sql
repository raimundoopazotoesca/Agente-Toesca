-- 013_valor_cuota_superseded.sql
-- Agregar superseded_at a raw_valor_cuota_line para permitir invalidar
-- valores de fuente CDG cuando existe una versión EEFF más confiable.
ALTER TABLE raw_valor_cuota_line ADD COLUMN superseded_at TEXT;
