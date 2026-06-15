-- Schema v2: clean, no redundancies
-- Replaces the incremental migrations 001-018

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ─────────────────────────────────────────
-- DIMENSIONS
-- ─────────────────────────────────────────
CREATE TABLE dim_fondo (
    fondo_key        TEXT PRIMARY KEY,
    nombre           TEXT NOT NULL,
    sharepoint_folder TEXT
);

CREATE TABLE dim_activo (
    activo_key    TEXT PRIMARY KEY,
    fondo_key     TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nombre        TEXT NOT NULL,
    tipo          TEXT,
    participacion REAL,
    categoria     TEXT,
    sociedad      TEXT
);

CREATE TABLE dim_serie (
    nemotecnico  TEXT PRIMARY KEY,
    fondo_key    TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    serie        TEXT NOT NULL,
    transa_bolsa INTEGER NOT NULL DEFAULT 0
);

-- ─────────────────────────────────────────
-- RAW — una tabla por tipo de documento fuente
-- ─────────────────────────────────────────

-- EEFF fondo (trimestral, desde PDFs/EEFF TRI/PT/APO)
CREATE TABLE raw_eeff_line (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key     TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    periodo       TEXT NOT NULL,   -- YYYY-MM
    cuenta_codigo TEXT,
    cuenta_nombre TEXT,
    monto_clp     REAL,
    monto_uf      REAL,
    source_file   TEXT,
    source_sheet  TEXT,
    source_row    INTEGER,
    file_hash     TEXT,
    ingest_run_id INTEGER REFERENCES ingest_run(id),
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT
);

-- Estado de Resultados por activo (mensual, desde EEFF Curicó/Viña/INMOSA)
CREATE TABLE raw_er_activo_line (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo        TEXT NOT NULL,   -- YYYY-MM
    cuenta_codigo  TEXT,
    cuenta_nombre  TEXT,
    monto_clp      REAL,
    monto_uf       REAL,
    seccion        TEXT,
    es_operacional INTEGER,
    source_file    TEXT,
    source_sheet   TEXT,
    source_row     INTEGER,
    file_hash      TEXT,
    ingest_run_id  INTEGER REFERENCES ingest_run(id),
    loaded_at      TEXT DEFAULT (datetime('now')),
    superseded_at  TEXT
);

-- Flujos de caja por activo
CREATE TABLE raw_flujo_line (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key    TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo       TEXT NOT NULL,
    cuenta_codigo TEXT,
    cuenta_nombre TEXT,
    monto_clp     REAL,
    monto_uf      REAL,
    source_file   TEXT,
    source_sheet  TEXT,
    source_row    INTEGER,
    file_hash     TEXT,
    ingest_run_id INTEGER REFERENCES ingest_run(id),
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT
);

-- Rent roll por activo
CREATE TABLE raw_rent_roll_line (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key    TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo       TEXT NOT NULL,
    unidad        TEXT,
    arrendatario  TEXT,
    m2            REAL,
    renta_uf      REAL,
    vencimiento   TEXT,
    extra_json    TEXT,
    source_file   TEXT,
    source_sheet  TEXT,
    source_row    INTEGER,
    file_hash     TEXT,
    ingest_run_id INTEGER REFERENCES ingest_run(id),
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT
);

-- Dividendos por serie (UF y CLP por cuota)
-- Unifica: raw_dividendo_line (TRI) + fact_dividendo (PT)
CREATE TABLE raw_dividendo_line (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key      TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nemotecnico    TEXT NOT NULL,
    fecha_pago     TEXT NOT NULL,
    monto_uf_cuota  REAL,
    monto_clp_cuota REAL,
    periodo        TEXT,
    source_file    TEXT,
    file_hash      TEXT,
    loaded_at      TEXT DEFAULT (datetime('now')),
    superseded_at  TEXT
);

-- Valor cuota contable y bursátil + cuotas en circulación (tipo: 'contable'|'bursatil')
CREATE TABLE raw_valor_cuota_line (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key     TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nemotecnico   TEXT NOT NULL,
    fecha         TEXT NOT NULL,
    tipo          TEXT NOT NULL,   -- 'contable' | 'bursatil'
    precio_clp    REAL,
    precio_uf     REAL,
    uf_dia        REAL,
    cuotas        REAL,
    periodo       TEXT,
    source_file   TEXT,
    file_hash     TEXT,
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT
);

-- Capital suscrito por serie y periodo
CREATE TABLE raw_capital_suscrito_line (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key           TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nemotecnico         TEXT NOT NULL,
    fecha_fin_periodo   TEXT NOT NULL,
    capital_suscrito_uf REAL,
    periodo             TEXT,
    source_file         TEXT,
    file_hash           TEXT,
    loaded_at           TEXT DEFAULT (datetime('now'))
);

-- Precios bolsa scrapeados (renombrado desde fact_precio_cuota)
CREATE TABLE raw_precio_cuota_line (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nemotecnico TEXT NOT NULL,
    fecha       TEXT NOT NULL,
    precio_clp  REAL,
    fuente      TEXT,
    loaded_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(nemotecnico, fecha)
);

-- ─────────────────────────────────────────
-- DERIVED — solo cache de KPIs costosos
-- ─────────────────────────────────────────
CREATE TABLE derived_kpi (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad_tipo TEXT NOT NULL,
    entidad_key  TEXT NOT NULL,
    periodo      TEXT NOT NULL,
    kpi          TEXT NOT NULL,
    valor        REAL,
    unidad       TEXT,
    recipe       TEXT,
    ingest_run_id INTEGER,
    computed_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(entidad_tipo, entidad_key, periodo, kpi)
);

-- ─────────────────────────────────────────
-- INFRAESTRUCTURA
-- ─────────────────────────────────────────
CREATE TABLE ingest_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool        TEXT,
    source_file TEXT,
    file_hash   TEXT,
    rows_in     INTEGER,
    rows_loaded INTEGER,
    started_at  TEXT,
    ended_at    TEXT,
    status      TEXT,
    error       TEXT
);

CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO schema_version(version) VALUES (1);

-- ─────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────
CREATE INDEX idx_raw_eeff_fondo_periodo     ON raw_eeff_line(fondo_key, periodo);
CREATE INDEX idx_raw_er_activo_periodo      ON raw_er_activo_line(activo_key, periodo);
CREATE INDEX idx_raw_flujo_activo_periodo   ON raw_flujo_line(activo_key, periodo);
CREATE INDEX idx_raw_rr_activo_periodo      ON raw_rent_roll_line(activo_key, periodo);
CREATE INDEX idx_raw_div_nemo               ON raw_dividendo_line(nemotecnico, fecha_pago);
CREATE INDEX idx_raw_vc_nemo_fecha          ON raw_valor_cuota_line(nemotecnico, fecha);
CREATE INDEX idx_raw_precio_nemo_fecha      ON raw_precio_cuota_line(nemotecnico, fecha);
CREATE INDEX idx_derived_kpi_lookup         ON derived_kpi(entidad_tipo, entidad_key, periodo, kpi);
