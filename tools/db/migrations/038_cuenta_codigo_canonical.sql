-- Migration 038: agrega cuenta_codigo_canonical a raw_eeff_line
-- y crea dim_cuenta_eeff como tabla de referencia de cuentas canónicas.

ALTER TABLE raw_eeff_line ADD COLUMN cuenta_codigo_canonical TEXT;

CREATE INDEX IF NOT EXISTS idx_eeff_codigo_canonical
    ON raw_eeff_line (cuenta_codigo_canonical);

CREATE TABLE IF NOT EXISTS dim_cuenta_eeff (
    cuenta_codigo     TEXT PRIMARY KEY,   -- ej. 'ER.ingreso_arriendo'
    source_sheet      TEXT NOT NULL,      -- 'ER', 'ESF', 'EFE', 'ECP'
    grupo             TEXT NOT NULL,      -- 'ingreso', 'gasto', 'activo_corriente', etc.
    descripcion       TEXT NOT NULL,
    es_subtotal       INTEGER NOT NULL DEFAULT 0
);
