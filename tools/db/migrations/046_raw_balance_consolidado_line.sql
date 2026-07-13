-- Balance consolidado por fondo (TRI/PT/Apo): consolida EEFF de todas las
-- entidades/sociedades que componen el fondo (holding + subsidiarias), a
-- diferencia de raw_eeff_line que guarda el EEFF standalone del fondo.
-- El usuario ya calcula estos montos en su propia planilla — el agente NO
-- los recalcula, solo los persiste. Feed para fact sheets.
--
-- Reutiliza el catálogo dim_cuenta_eeff (sección ESF) en vez de texto libre,
-- para mantener consistencia con raw_eeff_line y permitir joins/agrupaciones
-- por el mismo cuenta_codigo/grupo/es_subtotal.

INSERT OR IGNORE INTO dim_cuenta_eeff (cuenta_codigo, seccion_eeff, grupo, descripcion, es_subtotal) VALUES
    ('ESF.otros_activos_no_corrientes', 'ESF', 'activo_no_corriente', 'Otros activos no corrientes', 0),
    ('ESF.pasivos_impuestos_diferidos', 'ESF', 'pasivo', 'Pasivos por impuestos diferidos', 0),
    ('ESF.activo_impuestos_diferidos', 'ESF', 'activo_no_corriente', 'Activo por impuestos diferidos', 0);

CREATE TABLE IF NOT EXISTS raw_balance_consolidado_line (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key     TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    periodo       TEXT NOT NULL,   -- YYYY-MM
    cuenta_codigo TEXT NOT NULL REFERENCES dim_cuenta_eeff(cuenta_codigo),
    monto_clp     REAL,
    source_file   TEXT,
    ingest_run_id INTEGER REFERENCES ingest_run(id),
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_raw_balance_consolidado_line_fondo_periodo
    ON raw_balance_consolidado_line(fondo_key, periodo);
