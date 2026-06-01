CREATE TABLE IF NOT EXISTS raw_deuda_saldo_line (
    run_id        TEXT,
    credito_key   TEXT NOT NULL,
    periodo       TEXT NOT NULL,
    saldo_uf      REAL,
    is_proyeccion INTEGER DEFAULT 0,
    PRIMARY KEY (credito_key, periodo)
);

CREATE INDEX IF NOT EXISTS idx_deuda_saldo_periodo ON raw_deuda_saldo_line (periodo);
CREATE INDEX IF NOT EXISTS idx_deuda_saldo_credito  ON raw_deuda_saldo_line (credito_key);
