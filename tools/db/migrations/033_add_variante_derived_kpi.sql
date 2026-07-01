-- Migration 033: agregar variante a derived_kpi y cambiar UNIQUE constraint.
-- variante='contable'|'bursatil' para KPIs con doble precio; NULL para el resto.
-- Nuevo PK lógico: (entidad_tipo, entidad_key, periodo, kpi, variante).

ALTER TABLE derived_kpi ADD COLUMN variante TEXT DEFAULT NULL;

DROP INDEX IF EXISTS idx_kpi_entidad;
DROP INDEX IF EXISTS idx_kpi_periodo;
DROP INDEX IF EXISTS idx_kpi_kpi;

DROP TABLE IF EXISTS derived_kpi_new;

CREATE TABLE derived_kpi_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad_tipo    TEXT NOT NULL CHECK (entidad_tipo IN ('fondo','activo','serie')),
    entidad_key     TEXT NOT NULL,
    periodo         TEXT NOT NULL,
    kpi             TEXT NOT NULL,
    variante        TEXT DEFAULT NULL,
    valor           REAL,
    unidad          TEXT,
    recipe          TEXT NOT NULL,
    ingest_run_id   INTEGER,
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (entidad_tipo, entidad_key, periodo, kpi, variante)
);

INSERT OR REPLACE INTO derived_kpi_new
    (id, entidad_tipo, entidad_key, periodo, kpi, variante,
     valor, unidad, recipe, ingest_run_id, computed_at)
SELECT  id, entidad_tipo, entidad_key, periodo, kpi, variante,
        valor, unidad, recipe, ingest_run_id, computed_at
FROM derived_kpi;

DROP TABLE derived_kpi;
ALTER TABLE derived_kpi_new RENAME TO derived_kpi;

CREATE INDEX idx_kpi_entidad ON derived_kpi(entidad_tipo, entidad_key);
CREATE INDEX idx_kpi_periodo ON derived_kpi(periodo);
CREATE INDEX idx_kpi_kpi     ON derived_kpi(kpi);
