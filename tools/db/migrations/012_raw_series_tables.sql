-- 012_raw_series_tables.sql
-- Formalizar tablas creadas inline en ingest_cdg_extract.py

CREATE TABLE IF NOT EXISTS raw_cuota_en_circulacion_line (
    id          INTEGER PRIMARY KEY,
    fondo_key   TEXT NOT NULL,
    nemotecnico TEXT NOT NULL,
    fecha       TEXT NOT NULL,
    cuotas      REAL NOT NULL,
    periodo     TEXT,
    source_file TEXT,
    file_hash   TEXT,
    loaded_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    superseded_at TEXT,
    UNIQUE(nemotecnico, fecha, file_hash)
);

CREATE TABLE IF NOT EXISTS raw_capital_suscrito_line (
    id                  INTEGER PRIMARY KEY,
    fondo_key           TEXT NOT NULL,
    nemotecnico         TEXT NOT NULL,
    fecha_fin_periodo   TEXT NOT NULL,
    capital_suscrito_uf REAL NOT NULL,
    periodo             TEXT,
    source_file         TEXT,
    file_hash           TEXT,
    loaded_at           TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(nemotecnico, fecha_fin_periodo, file_hash)
);
