-- 011_raw_valor_cuota_line.sql
CREATE TABLE IF NOT EXISTS raw_valor_cuota_line (
    id          INTEGER PRIMARY KEY,
    fondo_key   TEXT NOT NULL,
    nemotecnico TEXT NOT NULL,
    fecha       TEXT NOT NULL,          -- YYYY-MM-DD (último día del período)
    tipo        TEXT NOT NULL,          -- 'contable' | 'bursatil'
    precio_clp  REAL,                   -- CLP/cuota
    precio_uf   REAL,                   -- UF/cuota (precio_clp / uf_dia)
    uf_dia      REAL,                   -- UF del día
    cuotas      REAL,                   -- cuotas en circulación ese día
    periodo     TEXT,                   -- YYYY-MM
    source_file TEXT,
    file_hash   TEXT,
    loaded_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(nemotecnico, fecha, tipo, file_hash)
);
