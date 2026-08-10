-- 079: mercado de bodegas — snapshot semestral por zona (informe GPS
-- Property, texto pegado) + histórico semestral vacancia/UF (carga única
-- desde RAW/"mercado bodegas db.xlsx", ver
-- tools/db/backfill_mercado_bodegas_evolucion.py). Alimentan la tabla y el
-- gráfico "Mercado Bodegas" de la página 3 del fact sheet TRI.

CREATE TABLE raw_mercado_bodegas (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo               TEXT NOT NULL,   -- 'YYYY-MM', mes de cierre del semestre (06/12)
    zona                  TEXT NOT NULL,   -- 'Centro'|'Nor-Poniente'|'Norte'|'Poniente'|'Sur'|'Gran Santiago'
    clase                 TEXT,            -- 'A/B' (null para el total 'Gran Santiago')
    es_total              INTEGER DEFAULT 0,
    produccion_m2         REAL,
    inventario_final_m2   REAL,
    participacion_pct     REAL,            -- 4.6, no 0.046
    vacancia_actual_m2    REAL,
    tasa_vacancia_pct     REAL,
    vacancia_anterior_m2  REAL,
    absorcion_m2          REAL,
    precio_uf_m2          REAL,
    precio_usd_m2         REAL,
    file_hash             TEXT,
    source_row            INTEGER,
    ingest_run_id         INTEGER REFERENCES ingest_run(id),
    loaded_at             TEXT DEFAULT (datetime('now')),
    superseded_at         TEXT,
    UNIQUE(file_hash, source_row)
);

CREATE INDEX idx_mercado_bodegas_periodo ON raw_mercado_bodegas(periodo);
CREATE INDEX idx_mercado_bodegas_lookup ON raw_mercado_bodegas(periodo, zona)
    WHERE superseded_at IS NULL;

CREATE TABLE raw_mercado_bodegas_evolucion (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    semestre      TEXT NOT NULL,   -- '2S-2015', '1S-2016', ...
    anio          INTEGER NOT NULL,
    periodo_num   INTEGER NOT NULL,  -- 1|2
    uf_m2         REAL,
    vacancia_pct  REAL,            -- fracción, 0.0995 = 9.95%
    source_file   TEXT,
    file_hash     TEXT,
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT,
    UNIQUE(semestre, file_hash)
);

CREATE INDEX idx_mercado_bodegas_evolucion_semestre
    ON raw_mercado_bodegas_evolucion(semestre);
