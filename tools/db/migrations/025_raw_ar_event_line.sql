-- Eventos del Análisis y Registro (A&R) de cada fondo/serie.
-- Fuente: hoja "A&R Rentas" / "A&R PT" / "A&R Apoquindo" del CDG mensual.
--
-- Detalle posibles valores:
--   'Aporte'        → capital aportado por inversores (flujo negativo en XIRR)
--   'Dividendo'     → distribución de utilidades (flujo positivo)
--   'Disminución'   → devolución de capital (flujo positivo)
--   'Canje Cuotas'  → conversión entre series A↔C↔I (flujo = 0, excluir de XIRR)
--   'VR Contable'   → valor razonable contable del fondo en esa fecha (solo terminal)
--   'VR Bursátil'   → valor razonable bursátil (solo terminal, TIR bursátil)

CREATE TABLE IF NOT EXISTS raw_ar_event_line (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_key        TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
    nemotecnico      TEXT NOT NULL,
    fecha            TEXT NOT NULL,          -- YYYY-MM-DD
    detalle          TEXT NOT NULL,          -- ver valores arriba
    monto_uf         REAL,                   -- total UF del evento
    monto_uf_cuota   REAL,                   -- UF por cuota
    monto_clp        REAL,                   -- CLP total
    cuotas           REAL,                   -- cuotas involucradas
    source_file      TEXT,
    file_hash        TEXT NOT NULL,
    loaded_at        TEXT DEFAULT (datetime('now')),
    UNIQUE (fondo_key, nemotecnico, fecha, detalle, file_hash)
);

CREATE INDEX IF NOT EXISTS idx_ar_nemo_fecha  ON raw_ar_event_line (nemotecnico, fecha);
CREATE INDEX IF NOT EXISTS idx_ar_detalle     ON raw_ar_event_line (detalle);
