-- Movimientos de capital (aportes y disminuciones) del fondo TRI
-- Fuente: Estado de Cambios en el Patrimonio de los EEFF trimestrales
-- Granularidad: fondo total por período (el EEFF no desagrega por serie)

CREATE TABLE IF NOT EXISTS raw_capital_movimiento_line (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key        TEXT    NOT NULL,                       -- 'TRI'
    fecha_fin_periodo TEXT   NOT NULL,                       -- YYYY-MM-DD
    periodo          TEXT,                                   -- YYYY-MM
    tipo             TEXT    NOT NULL CHECK (tipo IN ('aporte', 'disminucion')),
    monto_mclp       REAL,                                   -- M$ (tal como aparece en EEFF)
    monto_clp        REAL,                                   -- monto_mclp * 1_000_000
    monto_uf         REAL,                                   -- monto_clp / uf_dia (si disponible)
    source_file      TEXT,
    file_hash        TEXT    NOT NULL,
    loaded_at        TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (fondo_key, fecha_fin_periodo, tipo, source_file)
);

CREATE INDEX IF NOT EXISTS idx_cap_mov_periodo
    ON raw_capital_movimiento_line (periodo);
