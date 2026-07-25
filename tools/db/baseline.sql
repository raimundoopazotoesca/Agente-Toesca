-- ════════════════════════════════════════════════════════════════════════════
-- BASELINE del esquema — equivale a aplicar las migraciones 001..060.
--
-- GENERADO POR scripts/regenerar_baseline.py — no editar a mano.
--
-- Por qué existe
-- --------------
-- La DB productiva nunca se construyó ejecutando las migraciones: se bootstrapeó
-- desde tools/db/schema_v2.sql (2026-06-01) y las versiones 2–22 se marcaron
-- aplicadas en un solo lote, con timestamp idéntico, sin ejecutarse. Resultado:
-- una DB nueva creada con apply_migrations() tenía un esquema DISTINTO del de
-- producción, y los tests validaban un esquema que producción no tenía.
--
-- Este archivo es el esquema real de producción. El runner lo aplica a una DB
-- vacía y registra 1..60 como aplicadas — ahora sí de forma veraz, porque el
-- baseline incorpora sus efectos. Las migraciones históricas se conservan como
-- referencia pero ya no se ejecutan sobre DBs nuevas.
--
-- Decisiones tomadas al construirlo
-- ---------------------------------
-- INCLUIDO: los 12 índices que las migraciones declaraban y producción no tenía
--   (recuperados en la migración 059; aditivos, sin efecto sobre datos).
--
-- EXCLUIDO — `dim_cuenta` (001/002): obsoleta, reemplazada por `dim_cuenta_eeff`.
--   Nunca existió en producción. Peor: las migraciones declaraban FK
--   `raw_{eeff,er_activo,flujo}_line.cuenta_codigo -> dim_cuenta(codigo)` sobre
--   una tabla que quedaba vacía, así que en una DB nueva **toda ingesta con
--   cuenta_codigo fallaba**. Se excluyen la tabla y esas tres FKs.
--
-- EXCLUIDO — `publish_run` (005): nunca se creó en producción ni se usó. Sus
--   únicos consumidores (`repo_audit.start/finish_publish_run`) fallaban con
--   "no such table" y se eliminaron.
--
-- PENDIENTE a propósito — `UNIQUE(file_hash, source_row)` en las 4 tablas raw
--   `_line`. La migración 002 lo declaraba y producción no lo tiene; por eso el
--   `INSERT OR IGNORE` de los repos es un no-op y hay duplicados vivos.
--   Imponerlo hoy fallaría. Entra tras el saneamiento (ROADMAP F0.4), en una
--   migración aplicada a producción y reflejada aquí a la vez.
-- ════════════════════════════════════════════════════════════════════════════


CREATE TABLE "derived_kpi" (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad_tipo    TEXT NOT NULL CHECK (entidad_tipo IN ('fondo','activo','serie')),
    entidad_key     TEXT NOT NULL,
    periodo         TEXT NOT NULL,
    kpi             TEXT NOT NULL,
    variante        TEXT DEFAULT NULL,
    valor           REAL,
    unidad          TEXT,
    formula          TEXT NOT NULL,
    ingest_run_id   INTEGER,
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (entidad_tipo, entidad_key, periodo, kpi, variante)
);

CREATE TABLE dim_activo (
    activo_key    TEXT PRIMARY KEY,
    fondo_key     TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nombre        TEXT NOT NULL,
    tipo          TEXT,
    participacion_fondo_activo REAL,
    categoria     TEXT,
    sociedad      TEXT
, sociedad_key TEXT REFERENCES dim_sociedad(sociedad_key), participacion_en_sociedad REAL, vigente_hasta TEXT);

CREATE TABLE dim_concepto_parking (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo      TEXT,                    -- '70500000-254', '363', '200', '253'
  nombre      TEXT NOT NULL,           -- 'Ingresos Efectivos (Neto)', 'MANTENCION SKYDATA', ...
  tipo        TEXT NOT NULL,           -- 'venta' | 'gasto'
  signo       INTEGER NOT NULL DEFAULT 1,   -- +1 | -1, informativo (columna B de la planilla)
  descripcion TEXT,
  activo      INTEGER NOT NULL DEFAULT 1,
  UNIQUE(codigo, nombre, signo)
);

CREATE TABLE dim_credito (
    credito_key         TEXT PRIMARY KEY,
    activo_key          TEXT NOT NULL,
    fondo_key           TEXT NOT NULL,
    sociedad            TEXT,
    acreedor            TEXT,
    tipo_deuda          TEXT,
    participacion_fondo_deuda          REAL,
    deuda_inicial_uf    REAL,
    tasa_anual          REAL,
    cuota_mensual_uf    REAL,
    fecha_inicio        TEXT,
    fecha_vencimiento   TEXT,
    estado              TEXT DEFAULT 'VIGENTE',
    encargado           TEXT,
    perfil_amortizacion TEXT
);

CREATE TABLE dim_cuenta_eeff (
    cuenta_codigo     TEXT PRIMARY KEY,   -- ej. 'ER.ingreso_arriendo'
    seccion_eeff      TEXT NOT NULL,      -- 'ER', 'ESF', 'EFE', 'ECP'
    grupo             TEXT NOT NULL,      -- 'ingreso', 'gasto', 'activo_corriente', etc.
    descripcion       TEXT NOT NULL,
    es_subtotal       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE dim_fondo (
    fondo_key        TEXT PRIMARY KEY,
    nombre           TEXT NOT NULL,
    sharepoint_folder TEXT
, fondo_padre TEXT REFERENCES dim_fondo(fondo_key), participacion_en_padre REAL);

CREATE TABLE dim_serie (
    nemotecnico  TEXT PRIMARY KEY,
    fondo_key    TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    serie        TEXT NOT NULL,
    transa_bolsa INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE dim_sociedad (
  sociedad_key TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  fondo_key TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
  participacion_fondo_en_sociedad REAL NOT NULL
);

CREATE TABLE fact_adquisicion (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key           TEXT    NOT NULL REFERENCES dim_activo(activo_key),
    fecha_adquisicion    TEXT    NOT NULL,   -- YYYY-MM-DD
    precio_uf            REAL,               -- precio pagado por la participación del fondo (UF)
    valor_activo_uf      REAL,               -- valor 100% del activo en la compra (UF)
    superficie_m2        REAL,               -- superficie total (m²)
    uf_m2                REAL,               -- UF/m² basado en valor 100%
    porcentaje_adquirido REAL,               -- % del activo adquirido (ej. 0.333 para PT)
    notas                TEXT,
    loaded_at            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ingest_run_id        INTEGER REFERENCES ingest_run(id),
    UNIQUE(activo_key)
);

CREATE TABLE fact_tasacion (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key      TEXT    NOT NULL REFERENCES dim_activo(activo_key),
    periodo         TEXT    NOT NULL,   -- YYYY
    fecha           TEXT,               -- YYYY-MM-DD (fecha exacta del informe)
    tasador         TEXT    NOT NULL,   -- empresa tasadora (ej. JLL, CBRE, Colliers)
    valor_uf        REAL,               -- valor tasado total (UF al 100% del activo)
    superficie_m2   REAL,               -- superficie total tasada (m²)
    uf_m2           REAL,               -- UF/m² (valor_uf / superficie_m2)
    variacion_pct   REAL,               -- % variación vs período anterior (misma tasadora si aplica)
    tasa_dcto       REAL,               -- tasa de descuento usada (% anual)
    cap_rate        REAL,               -- cap rate de la tasación (%)
    ltv             REAL,               -- loan-to-value al momento de la tasación (%)
    ltc             REAL,               -- loan-to-cost (%)
    leverage_fin    REAL,               -- leverage financiero
    notas           TEXT,
    loaded_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ingest_run_id   INTEGER REFERENCES ingest_run(id),
    UNIQUE(activo_key, periodo, tasador)
);

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
, periodo_declarado TEXT, fecha_publicacion TEXT);

CREATE TABLE "raw_amortizacion" (
    credito_key  TEXT NOT NULL,
    periodo      TEXT NOT NULL,  -- YYYY-MM
    capital_uf   REAL,
    intereses_uf REAL,
    saldo_uf     REAL,
    PRIMARY KEY (credito_key, periodo)
);

CREATE TABLE "raw_ar_event" (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key        TEXT NOT NULL,
    nemotecnico      TEXT NOT NULL,
    fecha            TEXT NOT NULL,
    detalle          TEXT NOT NULL,
    monto_uf         REAL,
    monto_uf_cuota   REAL,
    monto_clp        REAL,
    cuotas           REAL,
    source_file      TEXT,
    file_hash        TEXT NOT NULL,
    loaded_at        TEXT,
    UNIQUE (fondo_key, nemotecnico, fecha, detalle, file_hash)
);

CREATE TABLE raw_balance_consolidado_line (
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

CREATE TABLE "raw_caja" (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key   TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    fecha       TEXT NOT NULL,   -- YYYY-MM-DD
    saldo_clp   REAL NOT NULL,
    source_file TEXT,
    loaded_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(fondo_key, fecha)
);

CREATE TABLE "raw_capital_suscrito" (
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

CREATE TABLE "raw_cuota_en_circulacion" (
    id          INTEGER PRIMARY KEY,
    fondo_key   TEXT NOT NULL,
    nemotecnico TEXT NOT NULL,
    fecha       TEXT NOT NULL,
    cuotas      REAL NOT NULL,
    periodo     TEXT,
    source_file TEXT,
    file_hash   TEXT,
    loaded_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    superseded_at TEXT,
    UNIQUE(nemotecnico, fecha, file_hash)
);

CREATE TABLE "raw_dividendo" (
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
, tipo TEXT NOT NULL DEFAULT 'dividendo');

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
, cuenta_codigo_canonical TEXT);

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

CREATE TABLE raw_mercado_oficinas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo             TEXT NOT NULL,        -- 'YYYY-MM', último mes del trimestre
    proveedor           TEXT NOT NULL,        -- 'JLL'
    submercado          TEXT NOT NULL,        -- 'Las Condes (CBD)', 'Providencia', etc.
    clase               TEXT NOT NULL,        -- 'Total', 'A', 'B'
    es_total            INTEGER DEFAULT 0,    -- 1 para filas 'Santiago' (agregado)
    inventario_m2       REAL,
    absorcion_trim_m2   REAL,
    absorcion_u12m_m2   REAL,
    vacancia_pct        REAL,                 -- 5.6, no 0.056
    renta_uf_m2         REAL,
    renta_usd_m2        REAL,
    produccion_trim_m2  REAL,
    produccion_u12m_m2  REAL,
    construccion_m2     REAL,
    file_hash           TEXT,
    source_row          INTEGER,
    ingest_run_id       INTEGER REFERENCES ingest_run(id),
    loaded_at           TEXT DEFAULT (datetime('now')),
    superseded_at       TEXT,
    UNIQUE(file_hash, source_row)
);

CREATE TABLE raw_pagare_intercompania (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    acreedor_fondo    TEXT,
    deudor_sociedad   TEXT,
    tipo              TEXT,
    fecha_inicio      TEXT,
    fecha_vencimiento TEXT,
    monto_uf          REAL,
    tasa_anual              REAL,
    saldo_c_intereses REAL
);

CREATE TABLE raw_parking_facturacion_line (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
  periodo        TEXT NOT NULL,
  concepto       TEXT NOT NULL,   -- 'saba_neto' | 'saba_iva' | 'saba_bruto'
                                  -- 'liquidacion_neto' | 'liquidacion_iva' | 'liquidacion_bruto'
                                  -- 'pago_a_pt'
  monto_clp      REAL NOT NULL,
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT,
  UNIQUE(activo_key, periodo, concepto, superseded_at)
);

CREATE TABLE raw_parking_gasto_line (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
  periodo        TEXT NOT NULL,
  concepto_id    INTEGER NOT NULL REFERENCES dim_concepto_parking(id),
  monto_clp      REAL NOT NULL,
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT,
  UNIQUE(activo_key, periodo, concepto_id, superseded_at)
);

CREATE TABLE raw_parking_ingreso_line (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
  periodo        TEXT NOT NULL,        -- 'YYYY-MM'
  concepto_id    INTEGER NOT NULL REFERENCES dim_concepto_parking(id),
  monto_clp      REAL NOT NULL,        -- valor tal como viene en la planilla (signo ya incluido en la celda)
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT,
  UNIQUE(activo_key, periodo, concepto_id, superseded_at)
);

CREATE TABLE raw_parking_ticket_line (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
  fecha          TEXT NOT NULL,        -- 'YYYY-MM-DD'
  tickets        INTEGER NOT NULL,
  feriado        INTEGER NOT NULL DEFAULT 0,   -- 0/1
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT, monto_bruto_clp REAL,
  UNIQUE(activo_key, fecha, superseded_at)
);

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

CREATE TABLE "raw_saldo_deuda" (
    run_id        TEXT,
    credito_key   TEXT NOT NULL,
    periodo       TEXT NOT NULL,
    saldo_uf      REAL,
    is_proyeccion INTEGER DEFAULT 0,
    PRIMARY KEY (credito_key, periodo)
);

CREATE TABLE raw_uf_diaria (
    fecha     TEXT PRIMARY KEY,        -- ISO YYYY-MM-DD
    valor     REAL NOT NULL,           -- CLP por UF
    fuente    TEXT NOT NULL,           -- 'CMF' | 'SII' | ...
    loaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE "raw_valor_cuota_bursatil" (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nemotecnico TEXT NOT NULL,
    fecha       TEXT NOT NULL,
    precio_clp  REAL,
    fuente      TEXT,
    loaded_at   TEXT DEFAULT (datetime('now')), uf_dia   REAL, precio_uf REAL, cuotas          REAL, patrimonio_bursatil_uf REAL,
    UNIQUE(nemotecnico, fecha)
);

CREATE TABLE "raw_valor_cuota_contable" (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key     TEXT,
    nemotecnico   TEXT NOT NULL,
    fecha         TEXT NOT NULL,
    precio_clp    REAL,
    precio_uf     REAL,
    uf_dia        REAL,
    cuotas        REAL,
    periodo       TEXT,
    source_file   TEXT,
    file_hash     TEXT,
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT,
    UNIQUE(nemotecnico, fecha, source_file)
);

CREATE INDEX idx_amort_credito  ON "raw_amortizacion" (credito_key);

CREATE INDEX idx_amort_periodo  ON "raw_amortizacion" (periodo);

CREATE INDEX idx_ar_detalle ON "raw_ar_event" (detalle);

CREATE INDEX idx_ar_nemo_fecha ON "raw_ar_event" (nemotecnico, fecha);

CREATE INDEX idx_caja_fondo_fecha ON "raw_caja"(fondo_key, fecha);

CREATE UNIQUE INDEX idx_capital_suscrito_unico
    ON "raw_capital_suscrito"(fondo_key, nemotecnico, fecha_fin_periodo, capital_suscrito_uf, file_hash);

CREATE INDEX idx_deuda_saldo_credito  ON "raw_saldo_deuda" (credito_key);

CREATE INDEX idx_deuda_saldo_periodo ON "raw_saldo_deuda" (periodo);

CREATE INDEX idx_dim_activo_fondo      ON dim_activo(fondo_key);

CREATE INDEX idx_dim_serie_fondo       ON dim_serie(fondo_key);

CREATE INDEX idx_dividendo_nemo_fecha_tipo ON "raw_dividendo" (nemotecnico, fecha_pago, tipo);

CREATE INDEX idx_eeff_codigo_canonical
    ON raw_eeff_line (cuenta_codigo_canonical);

CREATE INDEX idx_ingest_run_hash       ON ingest_run(file_hash);

CREATE INDEX idx_kpi_entidad ON derived_kpi(entidad_tipo, entidad_key);

CREATE INDEX idx_kpi_kpi     ON derived_kpi(kpi);

CREATE INDEX idx_kpi_periodo ON derived_kpi(periodo);

CREATE INDEX idx_mercado_lookup ON raw_mercado_oficinas(periodo, submercado, clase)
    WHERE superseded_at IS NULL;

CREATE INDEX idx_mercado_periodo ON raw_mercado_oficinas(periodo);

CREATE INDEX idx_raw_div_nemo               ON "raw_dividendo"(nemotecnico, fecha_pago);

CREATE INDEX idx_raw_eeff_cuenta       ON raw_eeff_line(cuenta_codigo);

CREATE INDEX idx_raw_eeff_fondo_periodo     ON raw_eeff_line(fondo_key, periodo);

CREATE INDEX idx_raw_eeff_hash         ON raw_eeff_line(file_hash);

CREATE INDEX idx_raw_eeff_periodo      ON raw_eeff_line(periodo);

CREATE INDEX idx_raw_er_activo_hash    ON raw_er_activo_line(file_hash);

CREATE INDEX idx_raw_er_activo_noi     ON raw_er_activo_line(activo_key, periodo, es_operacional);

CREATE INDEX idx_raw_er_activo_periodo      ON raw_er_activo_line(activo_key, periodo);

CREATE INDEX idx_raw_er_cuenta         ON raw_er_activo_line(cuenta_codigo);

CREATE INDEX idx_raw_er_periodo        ON raw_er_activo_line(periodo);

CREATE INDEX idx_raw_flujo_activo_periodo   ON raw_flujo_line(activo_key, periodo);

CREATE INDEX idx_raw_flujo_hash        ON raw_flujo_line(file_hash);

CREATE INDEX idx_raw_rr_activo_periodo      ON raw_rent_roll_line(activo_key, periodo);

CREATE INDEX idx_raw_rr_hash           ON raw_rent_roll_line(file_hash);

CREATE INDEX idx_raw_valor_cuota_bursatil_nemo_fecha ON "raw_valor_cuota_bursatil"(nemotecnico, fecha);

CREATE INDEX idx_raw_vc_contable_nemo_fecha
    ON "raw_valor_cuota_contable"(nemotecnico, fecha);

CREATE INDEX idx_tasacion_activo_periodo
    ON fact_tasacion(activo_key, periodo);

CREATE INDEX ix_raw_balance_consolidado_line_fondo_periodo
    ON raw_balance_consolidado_line(fondo_key, periodo);

CREATE INDEX ix_raw_uf_diaria_fecha ON raw_uf_diaria(fecha);

CREATE UNIQUE INDEX uq_derived_kpi_logical
    ON derived_kpi (
        entidad_tipo,
        entidad_key,
        periodo,
        kpi,
        COALESCE(variante, '')
    );

CREATE VIEW fact_dividendo AS
SELECT
    nemotecnico,
    fecha_pago,
    monto_clp_cuota  AS monto,
    monto_uf_cuota   AS monto_uf,
    periodo,
    fondo_key
FROM "raw_dividendo"
WHERE superseded_at IS NULL
  AND tipo = 'dividendo';

CREATE VIEW fact_precio_cuota AS
SELECT
    nemotecnico,
    fecha,
    precio_clp   AS precio,
    fuente
FROM "raw_valor_cuota_bursatil";

CREATE VIEW fact_uf AS
SELECT fecha, valor
FROM raw_uf_diaria
ORDER BY fecha;

CREATE VIEW "raw_amortizacion_line" AS SELECT * FROM "raw_amortizacion";

CREATE VIEW "raw_ar_event_line" AS SELECT * FROM "raw_ar_event";

CREATE VIEW "raw_caja_line" AS SELECT * FROM "raw_caja";

CREATE VIEW "raw_capital_suscrito_line" AS SELECT * FROM "raw_capital_suscrito";

CREATE VIEW "raw_cuota_en_circulacion_line" AS SELECT * FROM "raw_cuota_en_circulacion";

CREATE VIEW "raw_dividendo_line" AS SELECT * FROM "raw_dividendo";

CREATE VIEW "raw_saldo_deuda_line" AS SELECT * FROM "raw_saldo_deuda";

CREATE VIEW "raw_valor_cuota_bursatil_line" AS SELECT * FROM "raw_valor_cuota_bursatil";

CREATE VIEW "raw_valor_cuota_contable_line" AS SELECT * FROM "raw_valor_cuota_contable";

CREATE VIEW raw_valor_cuota_line AS
    SELECT nemotecnico, fecha, precio_uf, precio_clp, uf_dia, cuotas,
           'contable' AS tipo, fondo_key
      FROM raw_valor_cuota_contable
     WHERE superseded_at IS NULL
    UNION ALL
    SELECT nemotecnico, fecha, precio_uf, precio_clp, uf_dia, cuotas,
           'bursatil' AS tipo, NULL AS fondo_key
      FROM raw_valor_cuota_bursatil;

CREATE VIEW v_activo_fondo_efectivo AS
  SELECT
    a.activo_key,
    s.fondo_key AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad AS participacion_efectiva,
    'directa' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  WHERE a.sociedad_key IS NOT NULL
  UNION ALL
  SELECT
    a.activo_key,
    f.fondo_padre AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad * f.participacion_en_padre AS participacion_efectiva,
    'lookthrough' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  JOIN dim_fondo   f ON s.fondo_key    = f.fondo_key
  WHERE a.sociedad_key IS NOT NULL
    AND f.fondo_padre IS NOT NULL;

CREATE VIEW v_capital_suscrito_serie AS
WITH base AS (
    SELECT
        c.nemotecnico,
        c.fondo_key,
        c.fecha,
        c.periodo,
        MAX(c.cuotas)      AS cuotas,
        v.precio_clp       AS valor_cuota_clp,
        v.uf_dia           AS uf_dia
    FROM "raw_cuota_en_circulacion" c
    JOIN "raw_valor_cuota_contable" v
        ON  c.nemotecnico = v.nemotecnico
        AND c.fecha       = v.fecha
        AND v.superseded_at IS NULL
    WHERE c.superseded_at IS NULL
    GROUP BY c.nemotecnico, c.fondo_key, c.fecha, c.periodo,
             v.precio_clp, v.uf_dia
),
cs AS (
    SELECT nemotecnico, MAX(capital_suscrito_uf) AS capital_suscrito_uf
    FROM "raw_capital_suscrito"
    GROUP BY nemotecnico
)
SELECT
    b.nemotecnico,
    b.fondo_key,
    b.fecha,
    b.periodo,
    b.cuotas,
    b.valor_cuota_clp,
    b.uf_dia,
    ROUND(b.cuotas * b.valor_cuota_clp / NULLIF(b.uf_dia, 0), 4) AS patrimonio_contable_uf,
    cs.capital_suscrito_uf
FROM base b
LEFT JOIN cs ON cs.nemotecnico = b.nemotecnico;

CREATE VIEW v_flujos_tir_serie AS
SELECT
    r.nemotecnico,
    r.fecha_pago,
    r.tipo,
    r.monto_uf_cuota,
    r.monto_clp_cuota,
    r.periodo
FROM "raw_dividendo" r
WHERE r.superseded_at IS NULL
  AND r.fecha_pago LIKE '____-__-__'
  AND r.monto_uf_cuota IS NOT NULL
  AND r.monto_uf_cuota > 0
  AND r.id = (
      SELECT MAX(r2.id)
      FROM "raw_dividendo" r2
      WHERE r2.nemotecnico      = r.nemotecnico
        AND r2.fecha_pago       = r.fecha_pago
        AND r2.tipo             = r.tipo
        AND r2.superseded_at IS NULL
        AND r2.monto_uf_cuota IS NOT NULL
        AND r2.monto_uf_cuota > 0
  );

CREATE VIEW v_parking_mensual AS
SELECT
  i.activo_key,
  i.periodo,
  SUM(CASE WHEN c.tipo='venta' THEN i.monto_clp END) AS ingresos_totales_clp,
  (SELECT SUM(g.monto_clp)
     FROM raw_parking_gasto_line g
     JOIN dim_concepto_parking cg ON cg.id = g.concepto_id
    WHERE g.activo_key=i.activo_key AND g.periodo=i.periodo
      AND g.superseded_at IS NULL) AS gastos_totales_clp
FROM raw_parking_ingreso_line i
JOIN dim_concepto_parking c ON c.id = i.concepto_id
WHERE i.superseded_at IS NULL
GROUP BY i.activo_key, i.periodo;

CREATE VIEW v_parking_ocupacion_diaria AS
SELECT
  t.activo_key,
  t.fecha,
  substr(t.fecha, 1, 7) AS periodo,
  t.tickets,
  t.feriado,
  t.monto_bruto_clp,
  r.estacionamientos_no_abonados,
  t.monto_bruto_clp / 40.0 AS tiempo_total_min,
  8 * 60 * r.estacionamientos_no_abonados AS tiempo_disponible_min,
  (t.monto_bruto_clp / 40.0) / (8 * 60 * r.estacionamientos_no_abonados) AS ocupacion_diaria
FROM raw_parking_ticket_line t
CROSS JOIN v_parking_ratio_no_abonados r
WHERE t.superseded_at IS NULL;

CREATE VIEW v_parking_ocupacion_mensual AS
SELECT
  activo_key,
  periodo,
  COUNT(*) AS dias,
  SUM(tickets) AS tickets_mes,
  SUM(monto_bruto_clp) AS bruto_mes,
  SUM(tiempo_total_min) AS tiempo_total_min_mes,
  SUM(tiempo_disponible_min) AS tiempo_disponible_min_mes,
  SUM(tiempo_total_min) / SUM(tiempo_disponible_min) AS ocupacion_mensual
FROM v_parking_ocupacion_diaria
GROUP BY activo_key, periodo;

CREATE VIEW v_parking_ratio_no_abonados AS
WITH ult12 AS (
  SELECT DISTINCT periodo FROM raw_parking_ingreso_line
  WHERE activo_key = 'Parking PT'
  ORDER BY periodo DESC LIMIT 12
),
tot AS (
  SELECT
    SUM(CASE WHEN c.codigo != '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_variables_u12m,
    SUM(i.monto_clp) AS ingresos_totales_u12m
  FROM raw_parking_ingreso_line i
  JOIN dim_concepto_parking c ON c.id = i.concepto_id
  WHERE i.activo_key = 'Parking PT' AND i.superseded_at IS NULL
    AND i.periodo IN (SELECT periodo FROM ult12)
)
SELECT
  ingresos_variables_u12m,
  ingresos_totales_u12m,
  CAST(ingresos_variables_u12m AS REAL) / ingresos_totales_u12m AS ratio_variable,
  (CAST(ingresos_variables_u12m AS REAL) / ingresos_totales_u12m) * 502 AS estacionamientos_no_abonados
FROM tot;

CREATE VIEW v_parking_resultado_uf AS
WITH mensual AS (
  SELECT
    i.periodo,
    SUM(i.monto_clp) AS ingresos_netos_clp,
    SUM(CASE WHEN c.codigo != '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_variables_clp,
    SUM(CASE WHEN c.codigo = '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_abonados_clp
  FROM raw_parking_ingreso_line i
  JOIN dim_concepto_parking c ON c.id = i.concepto_id
  WHERE i.activo_key = 'Parking PT' AND i.superseded_at IS NULL
  GROUP BY i.periodo
),
gastos AS (
  SELECT periodo, SUM(monto_clp) AS gastos_netos_clp
  FROM raw_parking_gasto_line
  WHERE activo_key = 'Parking PT' AND superseded_at IS NULL
  GROUP BY periodo
),
uf_ult_dia AS (
  SELECT substr(fecha, 1, 7) AS periodo, MAX(fecha) AS last_fecha
  FROM raw_uf_diaria
  GROUP BY substr(fecha, 1, 7)
),
uf_mes AS (
  SELECT ud.periodo, u.valor AS uf_valor
  FROM uf_ult_dia ud
  JOIN raw_uf_diaria u ON u.fecha = ud.last_fecha
)
SELECT
  m.periodo,
  m.ingresos_netos_clp,
  g.gastos_netos_clp,
  m.ingresos_netos_clp - g.gastos_netos_clp AS resultado_neto_clp,
  u.uf_valor,
  (m.ingresos_netos_clp - g.gastos_netos_clp) / u.uf_valor AS resultado_neto_uf,
  m.ingresos_variables_clp / u.uf_valor AS ingresos_variables_uf,
  m.ingresos_abonados_clp / u.uf_valor AS ingresos_abonados_uf
FROM mensual m
JOIN gastos g ON g.periodo = m.periodo
JOIN uf_mes u ON u.periodo = m.periodo;

CREATE VIEW v_serie_patrimonio AS
WITH
cs_hist AS (
    SELECT nemotecnico, MAX(capital_suscrito_uf) AS capital_suscrito_uf
    FROM "raw_capital_suscrito"
    GROUP BY nemotecnico
),
val AS (
    SELECT
        fondo_key,
        nemotecnico,
        periodo,
        MAX(precio_uf)  AS valor_libro_uf,
        MAX(precio_clp) AS valor_libro_clp,
        MAX(uf_dia)     AS uf_dia,
        MAX(cuotas)     AS cuotas
    FROM "raw_valor_cuota_contable"
    WHERE superseded_at IS NULL
    GROUP BY fondo_key, nemotecnico, periodo
),
div_acc AS (
    SELECT nemotecnico,
           SUM(monto_uf_cuota) AS divs_acum_uf
    FROM "raw_dividendo"
    WHERE superseded_at IS NULL
    GROUP BY nemotecnico
)
SELECT
    v.fondo_key,
    v.nemotecnico,
    v.periodo,
    v.valor_libro_uf,
    v.valor_libro_clp,
    v.uf_dia,
    v.cuotas,
    ROUND(v.cuotas * v.valor_libro_uf, 2) AS patrimonio_libro_uf,
    cs.capital_suscrito_uf,
    da.divs_acum_uf
FROM val v
LEFT JOIN cs_hist cs ON cs.nemotecnico = v.nemotecnico
LEFT JOIN div_acc da ON da.nemotecnico = v.nemotecnico;


-- ── Seeds de dimensiones ───────────────────────────────────────────────


-- dim_fondo (3 filas)
INSERT OR IGNORE INTO dim_fondo (fondo_key, nombre, sharepoint_folder, fondo_padre, participacion_en_padre) VALUES
    ('TRI', 'Toesca Rentas Inmobiliarias Fondo de Inversión', 'Fondos\Rentas TRI', NULL, NULL),
    ('PT', 'Fondo Toesca Rentas Inmobiliarias PT', 'Fondos\Rentas PT', 'TRI', 0.3333333333333333),
    ('Apo', 'Fondo Toesca Rentas Inmob Apoquindo', 'Fondos\Rentas Apoquindo', 'TRI', 0.3);


-- dim_serie (5 filas)
INSERT OR IGNORE INTO dim_serie (nemotecnico, fondo_key, serie, transa_bolsa) VALUES
    ('CFITRIPT-E', 'PT', 'Única', 1),
    ('CFITOERI1A', 'TRI', 'A', 1),
    ('CFITOERI1C', 'TRI', 'C', 1),
    ('CFITOERI1I', 'TRI', 'I', 1),
    ('Apo', 'Apo', 'Única', 0);


-- dim_sociedad (8 filas)
INSERT OR IGNORE INTO dim_sociedad (sociedad_key, nombre, fondo_key, participacion_fondo_en_sociedad) VALUES
    ('Chanarcillo', 'Inmobiliaria Chañarcillo Ltda', 'TRI', 1.0),
    ('CuricoSpA', 'Power Center Curicó SpA', 'TRI', 0.8),
    ('SeniorAssist', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', 'TRI', 0.43),
    ('VCSpA', 'Inmobiliaria VC SpA / Viña Centro SpA (colapsada)', 'TRI', 1.0),
    ('TorreASA', 'Torre A S.A.', 'PT', 1.0),
    ('BlvdSpA', 'Inmobiliaria Boulevard PT SpA', 'PT', 1.0),
    ('ApoquindoSpA', 'Inmobiliaria Apoquindo SpA', 'Apo', 1.0),
    ('MachaliSpA', 'Strip Machalí (liquidado sept-2025)', 'TRI', 1.0);


-- dim_activo (19 filas)
INSERT OR IGNORE INTO dim_activo (activo_key, fondo_key, nombre, tipo, participacion_fondo_activo, categoria, sociedad, sociedad_key, participacion_en_sociedad, vigente_hasta) VALUES
    ('INMOSA', 'TRI', 'INMOSA', 'inmobiliario', 0.43, 'Residencias', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', 'SeniorAssist', 1.0, NULL),
    ('Viña Centro', 'TRI', 'Viña Centro', 'retail', 1.0, 'Centros Comerciales', 'Inmobiliaria Viña Centro SpA', 'VCSpA', 1.0, NULL),
    ('Mall Curicó', 'TRI', 'Mall Curicó', 'retail', 0.8, 'Centros Comerciales', 'Power Center Curicó SpA', 'CuricoSpA', 1.0, NULL),
    ('Apo3001', 'TRI', 'Apoquindo 3001', 'oficina', 1.0, 'Oficinas', 'Inmobiliaria Chañarcillo Ltda', 'Chanarcillo', 0.685, NULL),
    ('Sucden', 'TRI', 'Bodegas Maipú (Sucden)', 'industrial', 1.0, 'Industrial', 'Inmobiliaria Chañarcillo Ltda', 'Chanarcillo', 1.0, NULL),
    ('Torre A', 'PT', 'Torre A', 'oficina', 0.333, 'Oficinas', 'Torre A.S.A.', 'TorreASA', 1.0, NULL),
    ('Boulevard', 'PT', 'Boulevard PT', 'oficina', 0.333, 'Oficinas', 'Inmobiliaria Boulevard PT SpA', 'BlvdSpA', 1.0, NULL),
    ('Apo4501', 'Apo', 'Apoquindo 4501', 'oficina', 1.0, 'Oficinas', 'Inmobiliaria Apoquindo SpA', 'ApoquindoSpA', 1.0, NULL),
    ('Apo4700', 'Apo', 'Apoquindo 4700', 'oficina', 1.0, 'Oficinas', 'Inmobiliaria Apoquindo SpA', 'ApoquindoSpA', 1.0, NULL),
    ('Residencia Arturo Medina', 'TRI', 'Residencia Arturo Medina', 'residencia', 0.43, 'Residencias', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', NULL, NULL, NULL),
    ('Residencia Candil', 'TRI', 'Residencia Candil', 'residencia', 0.43, 'Residencias', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', NULL, NULL, NULL),
    ('Residencia Colombia', 'TRI', 'Residencia Colombia', 'residencia', 0.43, 'Residencias', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', NULL, NULL, NULL),
    ('Residencia Coventry', 'TRI', 'Residencia Coventry', 'residencia', 0.43, 'Residencias', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', NULL, NULL, NULL),
    ('Residencia Domingo Calderón', 'TRI', 'Residencia Domingo Calderón', 'residencia', 0.43, 'Residencias', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', NULL, NULL, NULL),
    ('Residencia Padre Errázuriz', 'TRI', 'Residencia Padre Errázuriz / Leonardo Da Vinci', 'residencia', 0.43, 'Residencias', 'Inmobiliaria e Inversiones Senior Assist Chile S.A.', NULL, NULL, NULL),
    ('Ed. Guardiamarina', 'TRI', 'Edificio Guardiamarina', 'residencial', 1.0, 'Residencias', 'Ed. Guardiamarina', NULL, NULL, NULL),
    ('Ed. Placilla', 'TRI', 'Edificio Placilla', 'residencial', 1.0, 'Residencias', 'Ed. Placilla', NULL, NULL, NULL),
    ('Strip Machalí', 'TRI', 'Strip Machalí', 'retail', NULL, 'Comercial', 'Strip Machalí (liquidado sept-2025)', 'MachaliSpA', 1.0, '2025-08'),
    ('Parking PT', 'PT', 'Parking Parque Titanium (SABA)', 'parking', 1.0, 'Parking', NULL, NULL, NULL, NULL);


-- dim_concepto_parking (20 filas)
INSERT OR IGNORE INTO dim_concepto_parking (id, codigo, nombre, tipo, signo, descripcion, activo) VALUES
    (1, '70500000-254', 'Ingresos Efectivos (Neto)', 'venta', 1, NULL, 1),
    (2, '70500001-256', 'Facturas Pre pago', 'venta', 1, NULL, 1),
    (3, '70500002-261', 'Ingresos Empresas (Neto)', 'venta', 1, NULL, 1),
    (4, '70500002-261', 'Notas de credito', 'venta', -1, NULL, 1),
    (5, '70500002-261', 'Facturas Post pago', 'venta', 1, NULL, 1),
    (6, '70500003-250', 'Abonados (Neto)', 'venta', 1, NULL, 1),
    (7, '70500003-250', 'Notas de credito', 'venta', -1, NULL, 1),
    (8, '363', 'MANTENCION SKYDATA 44 UF TITANIUM', 'gasto', -1, NULL, 1),
    (10, '253', 'ADM. ESTACIONAMIENTOS TITANIUM', 'gasto', -1, NULL, 1),
    (12, '200', 'Otros gastos', 'gasto', -1, NULL, 1),
    (14, '200', 'Tarifario', 'gasto', -1, NULL, 1),
    (15, '363', 'Horas extra', 'gasto', -1, NULL, 1),
    (19, '200', 'Facturación electronica 44,5 UF', 'gasto', -1, NULL, 1),
    (20, '363', 'Repuestos mantención', 'gasto', -1, NULL, 1),
    (21, '200', 'Licencia y habilitación transbank', 'gasto', -1, NULL, 1),
    (22, '363', 'Comisión vtas Transbank', 'gasto', -1, NULL, 1),
    (23, '363', 'Diferencia Comisión vtas Transbank', 'gasto', -1, NULL, 1),
    (24, '363', 'Comisión por ventas', 'gasto', -1, NULL, 1),
    (25, NULL, 'Ticket', 'gasto', -1, NULL, 1),
    (26, NULL, 'Otras mantenciones', 'gasto', -1, NULL, 1);


-- dim_cuenta_eeff (82 filas)
INSERT OR IGNORE INTO dim_cuenta_eeff (cuenta_codigo, seccion_eeff, grupo, descripcion, es_subtotal) VALUES
    ('ER.ingreso_arriendo', 'ER', 'ingreso', 'Ingresos por arriendo de bienes raíces', 0),
    ('ER.intereses_reajustes', 'ER', 'ingreso', 'Intereses y reajustes', 0),
    ('ER.ingresos_dividendos', 'ER', 'ingreso', 'Ingresos por dividendos', 0),
    ('ER.resultado_participacion', 'ER', 'ingreso', 'Resultado en inversiones valorizadas por método de participación', 0),
    ('ER.resultado_venta_instrumentos', 'ER', 'ingreso', 'Resultado en venta de instrumentos financieros', 0),
    ('ER.resultado_venta_inmuebles', 'ER', 'ingreso', 'Resultado por venta de inmuebles', 0),
    ('ER.var_valor_razonable_prop', 'ER', 'ingreso', 'Variaciones en valor razonable de propiedades de inversión', 0),
    ('ER.var_valor_razonable_activos', 'ER', 'ingreso', 'Cambios netos en valor razonable de activos financieros y pasivos financieros', 0),
    ('ER.diferencias_cambio', 'ER', 'ingreso', 'Diferencias de cambio netas sobre efectivo y equivalentes', 0),
    ('ER.total_ingresos_operacion', 'ER', 'subtotal', 'Total ingresos/(pérdidas) netos de la operación', 1),
    ('ER.comision_admin', 'ER', 'gasto', 'Comisión de administración', 0),
    ('ER.honorarios_custodia', 'ER', 'gasto', 'Honorarios por custodia y administración', 0),
    ('ER.remun_comite', 'ER', 'gasto', 'Remuneración del Comité de Vigilancia', 0),
    ('ER.costos_transaccion', 'ER', 'gasto', 'Costos de transacción', 0),
    ('ER.depreciaciones', 'ER', 'gasto', 'Depreciaciones', 0),
    ('ER.otros_gastos', 'ER', 'gasto', 'Otros gastos de operación', 0),
    ('ER.total_gastos_operacion', 'ER', 'subtotal', 'Total gastos de operación', 1),
    ('ER.utilidad_operacion', 'ER', 'subtotal', 'Utilidad/(Pérdida) de la operación', 1),
    ('ER.costos_financieros', 'ER', 'gasto', 'Costos financieros', 0),
    ('ER.utilidad_antes_impuesto', 'ER', 'subtotal', 'Utilidad/(Pérdida) antes de impuesto', 1),
    ('ER.resultado_ejercicio', 'ER', 'resultado', 'Resultado del ejercicio', 1),
    ('ER.ajustes_conversion', 'ER', 'resultado_integral', 'Ajustes por conversión', 0),
    ('ER.ajustes_participacion_oi', 'ER', 'resultado_integral', 'Ajustes provenientes de inversiones valorizadas por método de participación', 0),
    ('ER.cobertura_flujo_caja', 'ER', 'resultado_integral', 'Cobertura de Flujo de Caja', 0),
    ('ER.otros_ajustes_patrimonio', 'ER', 'resultado_integral', 'Otros Ajustes al Patrimonio Neto', 0),
    ('ER.total_resultado_integral', 'ER', 'resultado', 'Total resultado integral', 1),
    ('ER.total_ingresos_operacion_alt', 'ER', 'subtotal', 'Total ingresos/pérdidas de la operación (variantes de nombre)', 1),
    ('ER.resultado_participacion_alt', 'ER', 'ingreso', 'Resultado de inversiones valorizadas por método de participación (sin "en")', 0),
    ('ER.impuesto_ganancias_exterior', 'ER', 'gasto', 'Impuesto a las ganancias por inversiones en el exterior', 0),
    ('ER.otros_ingresos', 'ER', 'ingreso', 'Otros ingresos de la operación', 0),
    ('ESF.efectivo', 'ESF', 'activo_corriente', 'Efectivo y equivalentes al efectivo', 0),
    ('ESF.activos_financieros_vr_resultados', 'ESF', 'activo_corriente', 'Activos financieros a valor razonable con efecto en resultados', 0),
    ('ESF.activos_financieros_vr_ori', 'ESF', 'activo_corriente', 'Activos financieros a valor razonable con efecto en otros resultados integrales', 0),
    ('ESF.activos_costo_amortizado', 'ESF', 'activo_corriente', 'Activos financieros a costo amortizado', 0),
    ('ESF.inversiones_participacion', 'ESF', 'activo_no_corriente', 'Inversiones valorizadas por el método de la participación', 0),
    ('ESF.cuentas_cobrar', 'ESF', 'activo_corriente', 'Cuentas y documentos por cobrar por operaciones', 0),
    ('ESF.otros_activos_corrientes', 'ESF', 'activo_corriente', 'Otros activos corrientes', 0),
    ('ESF.total_activo_corriente', 'ESF', 'subtotal', 'Total activo corriente', 1),
    ('ESF.propiedades_inversion', 'ESF', 'activo_no_corriente', 'Propiedades de inversión', 0),
    ('ESF.total_activo_no_corriente', 'ESF', 'subtotal', 'Total activo no corriente', 1),
    ('ESF.total_activo', 'ESF', 'subtotal', 'Total activo', 1),
    ('ESF.prestamos', 'ESF', 'pasivo', 'Préstamos', 0),
    ('ESF.cuentas_pagar', 'ESF', 'pasivo_corriente', 'Cuentas y documentos por pagar por operaciones', 0),
    ('ESF.otros_documentos_pagar', 'ESF', 'pasivo', 'Otros documentos y cuentas por pagar', 0),
    ('ESF.pasivos_financieros_vr', 'ESF', 'pasivo', 'Pasivos financieros a valor razonable con efecto en resultados', 0),
    ('ESF.ingresos_anticipados', 'ESF', 'pasivo', 'Ingresos anticipados', 0),
    ('ESF.otros_pasivos', 'ESF', 'pasivo', 'Otros pasivos', 0),
    ('ESF.total_pasivo_corriente', 'ESF', 'subtotal', 'Total pasivo corriente', 1),
    ('ESF.total_pasivo_no_corriente', 'ESF', 'subtotal', 'Total pasivo no corriente', 1),
    ('ESF.total_pasivo', 'ESF', 'subtotal', 'Total pasivo', 1),
    ('ESF.patrimonio_neto', 'ESF', 'patrimonio', 'Total patrimonio neto', 1),
    ('ESF.total_pasivo_patrimonio', 'ESF', 'subtotal', 'Total pasivo y patrimonio neto', 1),
    ('ESF.resultado_ejercicio_esf', 'ESF', 'patrimonio', 'Resultado del ejercicio (en ESF, dentro de patrimonio)', 0),
    ('ESF.resultados_acumulados', 'ESF', 'patrimonio', 'Resultados acumulados', 0),
    ('ESF.otras_reservas', 'ESF', 'patrimonio', 'Otras reservas de patrimonio', 0),
    ('ESF.dividendos_provisorios_esf', 'ESF', 'patrimonio', 'Dividendos provisorios (deducción patrimonio)', 0),
    ('ESF.total_patrimonio', 'ESF', 'subtotal', 'Total patrimonio (alternativa a total patrimonio neto)', 1),
    ('ESF.remun_soc_admin_pasivo', 'ESF', 'pasivo_corriente', 'Remuneración Sociedad Administradora (pasivo)', 0),
    ('ESF.otros_activos', 'ESF', 'activo', 'Otros activos (corrientes y no corrientes)', 0),
    ('ESF.otros_cuentas_cobrar', 'ESF', 'activo_corriente', 'Otros documentos y cuentas por cobrar', 0),
    ('EFE.flujos_operacion', 'EFE', 'flujo', 'Flujos de efectivo netos de actividades de operación', 0),
    ('EFE.flujos_inversion', 'EFE', 'flujo', 'Flujos de efectivo netos de actividades de inversión', 0),
    ('EFE.flujos_financiamiento', 'EFE', 'flujo', 'Flujos de efectivo netos de actividades de financiamiento', 0),
    ('EFE.variacion_neta_efectivo', 'EFE', 'subtotal', 'Aumento (disminución) neto de efectivo y efectivo equivalente', 1),
    ('EFE.saldo_inicial_efectivo', 'EFE', 'referencia', 'Saldo inicial efectivo y equivalentes al efectivo', 0),
    ('EFE.saldo_final_efectivo', 'EFE', 'referencia', 'Saldo final efectivo y equivalentes al efectivo', 0),
    ('EFE.cobro_arrendamiento', 'EFE', 'flujo_operacion', 'Cobro de arrendamiento de bienes raíces', 0),
    ('EFE.dividendos_recibidos', 'EFE', 'flujo_inversion', 'Dividendos recibidos', 0),
    ('EFE.cobranza_cuentas', 'EFE', 'flujo_operacion', 'Cobranza de cuentas y documentos por cobrar', 0),
    ('EFE.compra_activos_fin', 'EFE', 'flujo_inversion', 'Compra de activos financieros', 0),
    ('EFE.venta_activos_fin', 'EFE', 'flujo_inversion', 'Venta de activos financieros', 0),
    ('EFE.venta_inmuebles', 'EFE', 'flujo_inversion', 'Venta de inmuebles', 0),
    ('EFE.prestamos_obtenidos', 'EFE', 'flujo_financiamiento', 'Préstamos obtenidos', 0),
    ('EFE.pago_prestamos', 'EFE', 'flujo_financiamiento', 'Pago de préstamos', 0),
    ('EFE.repartos_dividendos', 'EFE', 'flujo_financiamiento', 'Repartos de dividendos / patrimonio', 0),
    ('EFE.aportes_financiamiento', 'EFE', 'flujo_financiamiento', 'Aportes de capital (financiamiento)', 0),
    ('ECP.aportes', 'ECP', 'movimiento', 'Aportes del ejercicio', 0),
    ('ECP.dividendos_pagados', 'ECP', 'movimiento', 'Dividendos pagados', 0),
    ('ECP.disminucion_patrimonio', 'ECP', 'movimiento', 'Disminución de patrimonio', 0),
    ('ESF.otros_activos_no_corrientes', 'ESF', 'activo_no_corriente', 'Otros activos no corrientes', 0),
    ('ESF.pasivos_impuestos_diferidos', 'ESF', 'pasivo', 'Pasivos por impuestos diferidos', 0),
    ('ESF.activo_impuestos_diferidos', 'ESF', 'activo_no_corriente', 'Activo por impuestos diferidos', 0);
