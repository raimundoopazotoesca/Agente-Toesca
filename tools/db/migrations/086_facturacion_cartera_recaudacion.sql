-- 086: conceptos canónicos de facturación, cartera y recaudación.
--
-- Confirmado con el usuario 2026-08-28.
--
-- Los nombres son de CONCEPTO, no de proveedor. JLL es la primera fuente que
-- los alimenta, no su definición: mañana otra fuente puede poblar las mismas
-- tablas sin cambiar nada aguas abajo. Por eso `fuente_proveedor` es NOT NULL
-- desde el nacimiento (las tablas nacen vacías, así que sale gratis) y
-- `fuente_formato` distingue versiones de contrato del mismo proveedor.
--
-- Todas llevan lineage completo obligatorio (source_file/sheet/row, file_hash,
-- ingest_run_id, loaded_at, superseded_at) y un único parcial sobre las filas
-- vivas, siguiendo uq_rent_roll_vivo (tools/db/baseline.sql:621).
--
-- Grano de reemplazo de las tres: (fuente_proveedor, activo_key, periodo). El
-- proveedor entra en la clave para que una fuente no supersede los datos de
-- otra sobre el mismo activo y período.

-- Movimientos contables por tercero. Fuente JLL v2: hoja `AuxiliarContable`.
-- monto_uf es el dato CANÓNICO de este pipeline: viene en UF y se guarda en UF.
-- (Contraste con raw_er_activo_line.monto_clp, que para estos activos contiene
-- UF de facto pese al nombre; ese es el puente legacy, no la semántica nueva.)
--
-- El grano llega solo a (activo, tercero): en la fuente JLL v2 las columnas
-- `inmueble` y `centro_de_costo` vienen 100% vacías, así que no hay trazabilidad
-- a unidad/local. No inventar una.
CREATE TABLE raw_movimiento_contable_line (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key            TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo               TEXT NOT NULL,              -- YYYY-MM canónico
    fecha_fuente          TEXT,                       -- fecha original sin truncar
    rubro                 TEXT NOT NULL,              -- rubro_presupuestal de la fuente
    clasificacion         TEXT,                       -- Ingresos | Gastos | Gastos No Operacionales
    codigo_rubro          TEXT,
    tercero               TEXT,
    descripcion           TEXT,
    monto_uf              REAL NOT NULL,
    -- Mapeo a plan de cuentas del ER. NULL + 'unmapped' cuando el rubro todavía
    -- no tiene cuenta acordada: raw-first, la fila se persiste igual y se
    -- reporta como anomalía. Nunca se descarta ni se adivina el mapping.
    cuenta_codigo_mapeada TEXT,
    mapping_status        TEXT NOT NULL DEFAULT 'unmapped'
                          CHECK (mapping_status IN ('mapped', 'unmapped')),
    fuente_proveedor      TEXT NOT NULL,
    fuente_formato        TEXT,
    source_file           TEXT,
    source_sheet          TEXT,
    source_row            INTEGER,
    file_hash             TEXT,
    ingest_run_id         INTEGER REFERENCES ingest_run(id),
    loaded_at             TEXT DEFAULT (datetime('now')),
    superseded_at         TEXT
);

CREATE INDEX idx_raw_mov_activo_periodo
    ON raw_movimiento_contable_line(activo_key, periodo);
CREATE INDEX idx_raw_mov_scope
    ON raw_movimiento_contable_line(fuente_proveedor, activo_key, periodo);
CREATE INDEX idx_raw_mov_hash ON raw_movimiento_contable_line(file_hash);
CREATE UNIQUE INDEX uq_mov_contable_vivo
    ON raw_movimiento_contable_line (file_hash, source_row)
    WHERE superseded_at IS NULL;

-- Cartera de morosos con aging. Fuente JLL v2: hoja `Cartera`. Montos en UF.
CREATE TABLE raw_cartera_line (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key         TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo            TEXT NOT NULL,
    fecha_corte_fuente TEXT,
    cliente            TEXT,
    marca              TEXT,
    identificacion     TEXT,
    documento          TEXT,
    concepto           TEXT,
    inmueble           TEXT,
    fecha_vencimiento  TEXT,
    dias_vencimiento   INTEGER,
    vencido_1_30       REAL,
    vencido_31_60      REAL,
    vencido_61_90      REAL,
    vencido_mas_91     REAL,
    saldo_por_vencer   REAL,
    saldo_a_favor      REAL,
    total_cartera      REAL,
    fuente_proveedor   TEXT NOT NULL,
    fuente_formato     TEXT,
    source_file        TEXT,
    source_sheet       TEXT,
    source_row         INTEGER,
    file_hash          TEXT,
    ingest_run_id      INTEGER REFERENCES ingest_run(id),
    loaded_at          TEXT DEFAULT (datetime('now')),
    superseded_at      TEXT
);

CREATE INDEX idx_raw_cartera_activo_periodo ON raw_cartera_line(activo_key, periodo);
CREATE INDEX idx_raw_cartera_scope
    ON raw_cartera_line(fuente_proveedor, activo_key, periodo);
CREATE INDEX idx_raw_cartera_hash ON raw_cartera_line(file_hash);
CREATE UNIQUE INDEX uq_cartera_vivo
    ON raw_cartera_line (file_hash, source_row) WHERE superseded_at IS NULL;

-- Recaudación por activo y período. Fuente JLL v2: hoja `Recaudado`.
--
-- Deliberadamente NO se deriva un KPI `tasa_recaudacion`. Falta definir si el
-- valor es caja recibida en el mes o cobro de la facturación de ese mismo
-- período; sin vínculo factura/documento, recaudado/facturado no es una tasa de
-- cobranza por cohorte. Pendiente de contrato de negocio.
CREATE TABLE raw_recaudacion (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key         TEXT NOT NULL REFERENCES dim_activo(activo_key),
    periodo            TEXT NOT NULL,
    fecha_corte_fuente TEXT,
    monto_uf           REAL NOT NULL,
    fuente_proveedor   TEXT NOT NULL,
    fuente_formato     TEXT,
    source_file        TEXT,
    source_sheet       TEXT,
    source_row         INTEGER,
    file_hash          TEXT,
    ingest_run_id      INTEGER REFERENCES ingest_run(id),
    loaded_at          TEXT DEFAULT (datetime('now')),
    superseded_at      TEXT
);

CREATE INDEX idx_raw_recaudacion_activo_periodo ON raw_recaudacion(activo_key, periodo);
CREATE INDEX idx_raw_recaudacion_scope
    ON raw_recaudacion(fuente_proveedor, activo_key, periodo);
CREATE UNIQUE INDEX uq_recaudacion_vivo
    ON raw_recaudacion (file_hash, source_row) WHERE superseded_at IS NULL;
