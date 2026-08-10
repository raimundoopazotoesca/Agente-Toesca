-- 078: histórico trimestral vacancia/renta Oficinas Las Condes (Clase A/B).
--
-- Fuente: SharePoint RAW/"mercado oficinas DB.xlsx" (hoja única, filas
-- Vacancia A/B y Renta A/B, columnas 1Q2019..1Q2026). Alimenta los gráficos
-- "Evolución anual vacancia/renta Oficinas Las Condes" de la página 3 del
-- fact sheet TRI.
--
-- Distinta de raw_mercado_oficinas (informe trimestral JLL, todas las
-- comunas/clases, granularidad mensual reciente 2025-12+): esta tabla es
-- solo Las Condes A/B, con el histórico largo que raw_mercado_oficinas no
-- tiene. Cuando raw_mercado_oficinas acumule suficientes trimestres propios
-- para Las Condes A/B, evaluar consolidar ambas fuentes en una vista.
CREATE TABLE raw_mercado_oficinas_evolucion (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo       TEXT NOT NULL,   -- 'YYYY-MM', mes de cierre del trimestre (03/06/09/12)
    anio          INTEGER NOT NULL,
    trimestre     INTEGER NOT NULL,  -- 1..4
    submercado    TEXT NOT NULL DEFAULT 'Las Condes (CBD)',
    clase         TEXT NOT NULL,   -- 'A' | 'B'
    vacancia_pct  REAL,            -- fracción, ej. 0.034 = 3.4%
    renta_uf_m2   REAL,
    source_file   TEXT,
    source_sheet  TEXT,
    file_hash     TEXT,
    ingest_run_id INTEGER REFERENCES ingest_run(id),
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT,
    UNIQUE(periodo, submercado, clase, file_hash)
);

CREATE INDEX idx_raw_mercado_oficinas_evolucion_periodo
    ON raw_mercado_oficinas_evolucion(submercado, clase, periodo);
