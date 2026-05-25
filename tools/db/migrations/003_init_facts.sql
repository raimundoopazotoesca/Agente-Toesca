-- Facts: datos directos del mercado, fuente única.

CREATE TABLE fact_precio_cuota (
    nemotecnico  TEXT NOT NULL REFERENCES dim_serie(nemotecnico),
    fecha        TEXT NOT NULL,
    precio       REAL NOT NULL,
    fuente       TEXT,
    loaded_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (nemotecnico, fecha)
);

CREATE TABLE fact_uf (
    fecha      TEXT PRIMARY KEY,
    valor_clp  REAL NOT NULL,
    loaded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE fact_dividendo (
    nemotecnico  TEXT NOT NULL REFERENCES dim_serie(nemotecnico),
    fecha_pago   TEXT NOT NULL,
    monto        REAL NOT NULL,
    loaded_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (nemotecnico, fecha_pago)
);
