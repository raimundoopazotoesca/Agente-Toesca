-- Tabla dedicada de UF diaria. Antes fact_uf era una view sobre
-- raw_valor_cuota_contable_line.uf_dia (solo 45 fechas quarter-end).
-- Con esta tabla podemos poblar UF diaria desde CMF/SII y usarla
-- como single source of truth.

CREATE TABLE IF NOT EXISTS raw_uf_diaria (
    fecha     TEXT PRIMARY KEY,        -- ISO YYYY-MM-DD
    valor     REAL NOT NULL,           -- CLP por UF
    fuente    TEXT NOT NULL,           -- 'CMF' | 'SII' | ...
    loaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_raw_uf_diaria_fecha ON raw_uf_diaria(fecha);

-- Reemplazar view fact_uf para leer desde la tabla nueva
DROP VIEW IF EXISTS fact_uf;
CREATE VIEW fact_uf AS
SELECT fecha, valor
FROM raw_uf_diaria
ORDER BY fecha;
