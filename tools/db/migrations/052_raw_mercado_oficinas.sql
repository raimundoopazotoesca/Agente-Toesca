-- Datos de mercado de oficinas de proveedores externos (JLL), ingesta trimestral
-- copy-paste desde el PDF del informe. Una fila = una fila de la tabla del informe.

CREATE TABLE raw_mercado_oficinas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo             TEXT NOT NULL,        -- 'YYYY-MM', último mes del trimestre
    proveedor           TEXT NOT NULL,        -- 'JLL'
    submercado          TEXT NOT NULL,        -- 'Las Condes (CBD)', 'Providencia', etc.
    clase               TEXT NOT NULL,        -- 'Total', 'A', 'B'
    es_total            INTEGER DEFAULT 0,    -- 1 para filas 'Santiago' (agregado)
    inventario_m2       REAL,
    absorcion_trim_m2   REAL,
    absorcion_u12m_m2   REAL,
    vacancia_pct        REAL,                 -- 5.6, no 0.056
    renta_uf_m2         REAL,
    renta_usd_m2        REAL,
    produccion_trim_m2  REAL,
    produccion_u12m_m2  REAL,
    construccion_m2     REAL,
    file_hash           TEXT,
    source_row          INTEGER,
    ingest_run_id       INTEGER REFERENCES ingest_run(id),
    loaded_at           TEXT DEFAULT (datetime('now')),
    superseded_at       TEXT,
    UNIQUE(file_hash, source_row)
);

CREATE INDEX idx_mercado_periodo ON raw_mercado_oficinas(periodo);
CREATE INDEX idx_mercado_lookup ON raw_mercado_oficinas(periodo, submercado, clase)
    WHERE superseded_at IS NULL;
