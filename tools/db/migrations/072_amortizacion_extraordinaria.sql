-- 072: log de pagos extraordinarios (prepagos/bullet) sobre créditos vigentes.
--
-- No reemplaza raw_amortizacion (cronograma completo, recargado en bloque por
-- tools/db/ingest_financing.py desde el Excel maestro) — es un registro
-- independiente del evento en sí, para no perderlo entre un reload y el
-- siguiente. Ver docs/superpowers/specs/2026-07-27-amortizacion-extraordinaria-design.md.
CREATE TABLE raw_amortizacion_extraordinaria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    credito_key     TEXT NOT NULL REFERENCES dim_credito(credito_key),
    fecha           TEXT NOT NULL,        -- 'YYYY-MM-DD'
    periodo         TEXT NOT NULL,        -- 'YYYY-MM', derivado de fecha
    monto_uf        REAL NOT NULL,
    nota            TEXT,
    source_file     TEXT,
    file_hash       TEXT,
    ingest_run_id   INTEGER REFERENCES ingest_run(id),
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT
);
