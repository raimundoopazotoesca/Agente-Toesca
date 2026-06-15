CREATE TABLE IF NOT EXISTS raw_amortizacion_line (
    credito_key  TEXT NOT NULL,
    periodo      TEXT NOT NULL,  -- YYYY-MM
    capital_uf   REAL,
    intereses_uf REAL,
    saldo_uf     REAL,
    PRIMARY KEY (credito_key, periodo)
);

CREATE INDEX IF NOT EXISTS idx_amort_periodo  ON raw_amortizacion_line (periodo);
CREATE INDEX IF NOT EXISTS idx_amort_credito  ON raw_amortizacion_line (credito_key);
