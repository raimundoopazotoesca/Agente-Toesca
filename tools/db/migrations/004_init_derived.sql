-- Derived: KPIs calculados por el agente.

CREATE TABLE derived_kpi (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad_tipo    TEXT NOT NULL CHECK (entidad_tipo IN ('fondo','activo','serie')),
    entidad_key     TEXT NOT NULL,
    periodo         TEXT NOT NULL,
    kpi             TEXT NOT NULL,
    valor           REAL,
    unidad          TEXT,
    recipe          TEXT NOT NULL,
    ingest_run_id   INTEGER,
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (entidad_tipo, entidad_key, periodo, kpi, recipe)
);

CREATE INDEX idx_kpi_entidad     ON derived_kpi(entidad_tipo, entidad_key);
CREATE INDEX idx_kpi_periodo     ON derived_kpi(periodo);
CREATE INDEX idx_kpi_kpi         ON derived_kpi(kpi);
