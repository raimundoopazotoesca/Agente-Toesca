-- Soporte para TIR (XIRR) por serie.
--
-- 1. Agrega columna 'tipo' a raw_dividendo_line para distinguir:
--      'dividendo'   → distribución de utilidades
--      'devolucion'  → devolución de capital (disminución de capital)
--    Ambas son cash flows positivos para el inversionista en el cálculo XIRR.
--
-- 2. Vista v_flujos_tir_serie: versión limpia de raw_dividendo_line.
--    Filtra fechas ISO válidas (YYYY-MM-DD), montos positivos no nulos,
--    no superseded. Dedup por (nemotecnico, fecha_pago, tipo) tomando el
--    registro de mayor id (más reciente).

-- La tabla también era creada inline por ingestas históricas. Se formaliza
-- aquí antes del ALTER para que una DB nueva sea reproducible desde cero.
CREATE TABLE IF NOT EXISTS raw_dividendo_line (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key       TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nemotecnico     TEXT NOT NULL,
    fecha_pago      TEXT NOT NULL,
    monto_uf_cuota  REAL,
    monto_clp_cuota REAL,
    periodo         TEXT,
    source_file     TEXT,
    file_hash       TEXT,
    loaded_at       TEXT DEFAULT (datetime('now')),
    superseded_at   TEXT
);

ALTER TABLE raw_dividendo_line ADD COLUMN tipo TEXT NOT NULL DEFAULT 'dividendo';

CREATE INDEX IF NOT EXISTS idx_dividendo_nemo_fecha_tipo
    ON raw_dividendo_line (nemotecnico, fecha_pago, tipo);

CREATE VIEW IF NOT EXISTS v_flujos_tir_serie AS
SELECT
    r.nemotecnico,
    r.fecha_pago,
    r.tipo,
    r.monto_uf_cuota,
    r.monto_clp_cuota,
    r.periodo
FROM raw_dividendo_line r
WHERE r.superseded_at IS NULL
  AND r.fecha_pago LIKE '____-__-__'
  AND r.monto_uf_cuota IS NOT NULL
  AND r.monto_uf_cuota > 0
  AND r.id = (
      SELECT MAX(r2.id)
      FROM raw_dividendo_line r2
      WHERE r2.nemotecnico      = r.nemotecnico
        AND r2.fecha_pago       = r.fecha_pago
        AND r2.tipo             = r.tipo
        AND r2.superseded_at IS NULL
        AND r2.monto_uf_cuota IS NOT NULL
        AND r2.monto_uf_cuota > 0
  );
