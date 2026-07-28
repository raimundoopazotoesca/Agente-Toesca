-- Tabla dedicada de dólar observado diario (análoga a raw_uf_diaria).
-- Fuente: API que aporte el usuario (pendiente de conectar). Se usa para
-- convertir a CLP los saldos en USD de la planilla Saldo Caja + FFMM.

CREATE TABLE IF NOT EXISTS raw_dolar_diaria (
    fecha     TEXT PRIMARY KEY,        -- ISO YYYY-MM-DD
    valor     REAL NOT NULL,           -- CLP por USD
    fuente    TEXT NOT NULL,           -- 'mindicador' | ...
    loaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_raw_dolar_diaria_fecha ON raw_dolar_diaria(fecha);

DROP VIEW IF EXISTS fact_dolar;
CREATE VIEW fact_dolar AS
SELECT fecha, valor
FROM raw_dolar_diaria
ORDER BY fecha;
