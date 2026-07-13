-- Migration 032: tabla histórico de saldo caja por fondo.
-- Fuente: resumen semanal/mensual compartido por el usuario.
-- Unidad: CLP (saldo bancario + FFMM consolidado por fondo).
-- Usado para: tasa_arriendo_ajustada_contable y otros KPIs que requieren caja.

CREATE TABLE IF NOT EXISTS raw_caja_line (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key   TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    fecha       TEXT NOT NULL,   -- YYYY-MM-DD
    saldo_clp   REAL NOT NULL,
    source_file TEXT,
    loaded_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(fondo_key, fecha)
);

CREATE INDEX IF NOT EXISTS idx_caja_fondo_fecha ON raw_caja_line(fondo_key, fecha);
