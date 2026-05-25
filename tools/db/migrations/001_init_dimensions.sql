-- Dimensiones: catálogos estables del negocio.

CREATE TABLE dim_fondo (
    fondo_key          TEXT PRIMARY KEY,
    nombre             TEXT NOT NULL,
    sharepoint_folder  TEXT
);

CREATE TABLE dim_activo (
    activo_key  TEXT PRIMARY KEY,
    fondo_key   TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nombre      TEXT NOT NULL,
    tipo        TEXT
);

CREATE TABLE dim_serie (
    nemotecnico  TEXT PRIMARY KEY,
    fondo_key    TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    serie        TEXT NOT NULL
);

CREATE TABLE dim_cuenta (
    codigo      TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    tipo_eeff   TEXT,
    signo       INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_dim_activo_fondo ON dim_activo(fondo_key);
CREATE INDEX idx_dim_serie_fondo  ON dim_serie(fondo_key);
