-- 080: mercado de comercio minorista RM (CNC, mensual) — variaciones reales
-- acumuladas por categoría. Alimenta la tabla "Variaciones Reales
-- Acumuladas Total Locales RM (CNC)" de la página 3 del fact sheet TRI
-- (S.page3.centros_comerciales). Sin columnas de fuente/URL: no se
-- necesitan para esta tabla (a diferencia de raw_mercado_bodegas).

CREATE TABLE raw_mercado_comercio (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo                 TEXT NOT NULL,   -- 'YYYY-MM'
    categoria               TEXT NOT NULL,   -- una de las 7 categorías fijas (ver build_factsheet.py)
    variacion_acumulada_pct REAL,            -- fracción: 0.007 = 0,7%
    file_hash               TEXT,
    source_row              INTEGER,
    ingest_run_id           INTEGER REFERENCES ingest_run(id),
    loaded_at               TEXT DEFAULT (datetime('now')),
    superseded_at           TEXT,
    UNIQUE(periodo, categoria, file_hash)
);

CREATE INDEX idx_mercado_comercio_periodo ON raw_mercado_comercio(periodo);
CREATE INDEX idx_mercado_comercio_lookup ON raw_mercado_comercio(periodo, categoria)
    WHERE superseded_at IS NULL;
