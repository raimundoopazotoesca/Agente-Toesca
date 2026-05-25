-- Capa raw: una fila por línea del documento del proveedor.

CREATE TABLE raw_rent_roll_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo         TEXT NOT NULL,
    unidad          TEXT,
    arrendatario    TEXT,
    m2              REAL,
    renta_uf        REAL,
    vencimiento     TEXT,
    extra_json      TEXT,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_rr_activo_periodo ON raw_rent_roll_line(activo_key, periodo);
CREATE INDEX idx_raw_rr_hash           ON raw_rent_roll_line(file_hash);

CREATE TABLE raw_eeff_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key       TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    periodo         TEXT NOT NULL,
    cuenta_codigo   TEXT REFERENCES dim_cuenta(codigo),
    cuenta_nombre   TEXT,
    monto_clp       REAL,
    monto_uf        REAL,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_eeff_fondo_periodo ON raw_eeff_line(fondo_key, periodo);

CREATE TABLE raw_flujo_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo         TEXT NOT NULL,
    cuenta_codigo   TEXT REFERENCES dim_cuenta(codigo),
    cuenta_nombre   TEXT,
    monto_clp       REAL,
    monto_uf        REAL,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_flujo_activo_periodo ON raw_flujo_line(activo_key, periodo);

CREATE TABLE raw_er_activo_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo         TEXT NOT NULL,
    cuenta_codigo   TEXT REFERENCES dim_cuenta(codigo),
    cuenta_nombre   TEXT,
    monto_clp       REAL,
    monto_uf        REAL,
    source_file     TEXT,
    source_sheet    TEXT,
    source_row      INTEGER,
    file_hash       TEXT NOT NULL,
    ingest_run_id   INTEGER,
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT,
    UNIQUE (file_hash, source_row)
);

CREATE INDEX idx_raw_er_activo_periodo ON raw_er_activo_line(activo_key, periodo);
