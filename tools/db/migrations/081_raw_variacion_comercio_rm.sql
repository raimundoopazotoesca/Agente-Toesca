-- 081: variación real anual de ventas, Región Metropolitana, Total Locales
-- (CNC) — dos series: Total Comercio y Supermercado Tradicional. Fuente:
-- 2 XLSX históricos de CNC (Índice de Ventas del Comercio RM + Índice de
-- Ventas de Supermercados RM), sección "Total Locales" de cada uno.
-- Cada ingesta reemplaza la serie completa (CNC revisa retrospectivamente
-- meses anteriores) — no es acumulativo mes a mes.
-- Alimenta el gráfico "Variaciones reales acumuladas Total Locales RM (CNC)"
-- del fact sheet TRI (distinto de raw_mercado_comercio, que es acumulada
-- por 7 categorías).

CREATE TABLE raw_variacion_comercio_rm (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo                         TEXT NOT NULL,   -- 'YYYY-MM'
    total_comercio_var_anual        REAL,            -- fracción: 0.036 = 3,6%
    supermercado_tradicional_var_anual REAL,
    file_hash                       TEXT,
    ingest_run_id                   INTEGER REFERENCES ingest_run(id),
    loaded_at                       TEXT DEFAULT (datetime('now')),
    superseded_at                   TEXT,
    UNIQUE(periodo, file_hash)
);

CREATE INDEX idx_variacion_comercio_rm_periodo ON raw_variacion_comercio_rm(periodo);
CREATE INDEX idx_variacion_comercio_rm_lookup ON raw_variacion_comercio_rm(periodo)
    WHERE superseded_at IS NULL;
