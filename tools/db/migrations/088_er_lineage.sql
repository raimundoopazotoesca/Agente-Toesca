-- 088: lineage de raw_er_activo_line hasta su origen.
--
-- Confirmado con el usuario 2026-08-28.
--
-- Una fila de ER derivada de JLL v2 agrega movimientos por
-- (activo_key, periodo, rubro), así que proviene de N movimientos, no de uno.
-- Por eso el lineage a movimientos es una tabla puente y no una FK 1:1; el
-- lineage a reglas internas sí es 1:1 y va como columna. Nada de una columna
-- polimórfica que apunte a cualquiera de las dos tablas.

ALTER TABLE raw_er_activo_line ADD COLUMN origen TEXT
    CHECK (origen IS NULL OR origen IN ('jll_v2', 'regla_interna', 'legacy'));

-- Apunta a la VERSIÓN concreta de regla usada, para que el ER sea reproducible
-- aunque después se inserte una versión nueva de esa misma regla.
ALTER TABLE raw_er_activo_line ADD COLUMN origen_regla_id INTEGER
    REFERENCES dim_er_regla_interna(id);

CREATE INDEX IF NOT EXISTS idx_er_activo_origen
    ON raw_er_activo_line(origen, origen_regla_id);

-- Puente N:1. `aporte_uf` deja explícito cuánto puso cada movimiento en el
-- agregado, para poder auditar la derivación sin recomputarla.
CREATE TABLE raw_er_movimiento_lineage (
    er_line_id    INTEGER NOT NULL REFERENCES raw_er_activo_line(id),
    movimiento_id INTEGER NOT NULL REFERENCES raw_movimiento_contable_line(id),
    aporte_uf     REAL,
    loaded_at     TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (er_line_id, movimiento_id)
);

CREATE INDEX idx_er_lineage_movimiento
    ON raw_er_movimiento_lineage(movimiento_id);

-- La exclusividad de origen_regla_id se impone aquí; la contraparte para
-- 'jll_v2' (que exista al menos una fila puente) no es expresable como CHECK en
-- SQLite y va como test de invariante en tests/db/test_invariantes.py.
--
-- SQLite no permite ADD CONSTRAINT, y recrear raw_er_activo_line para un CHECK
-- costaría reescribir ~10k filas y sus índices. Se usa un trigger, que además
-- cubre el UPDATE.
CREATE TRIGGER trg_er_origen_regla_coherente_ins
AFTER INSERT ON raw_er_activo_line
WHEN (NEW.origen = 'regla_interna' AND NEW.origen_regla_id IS NULL)
  OR (NEW.origen IN ('jll_v2', 'legacy') AND NEW.origen_regla_id IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'origen_regla_id incoherente con origen');
END;

CREATE TRIGGER trg_er_origen_regla_coherente_upd
AFTER UPDATE ON raw_er_activo_line
WHEN (NEW.origen = 'regla_interna' AND NEW.origen_regla_id IS NULL)
  OR (NEW.origen IN ('jll_v2', 'legacy') AND NEW.origen_regla_id IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'origen_regla_id incoherente con origen');
END;
