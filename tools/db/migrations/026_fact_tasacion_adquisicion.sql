-- Tasaciones y valores de compra de activos inmobiliarios.
--
-- Diseño:
--   - fact_tasacion: una fila por (activo, periodo, tasador).
--     Cada año se contratan 2 tasadores; ambos quedan registrados.
--     El promedio se computa en consulta o se persiste en derived_kpi.
--   - fact_adquisicion: una fila por activo (compra única).
--
-- Períodos: YYYY (anual para tasaciones), YYYY-MM-DD para fechas exactas.

CREATE TABLE IF NOT EXISTS fact_tasacion (
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

CREATE INDEX IF NOT EXISTS idx_tasacion_activo_periodo
    ON fact_tasacion(activo_key, periodo);

-- Valor de compra — un evento por activo (adquisición única).
CREATE TABLE IF NOT EXISTS fact_adquisicion (
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
