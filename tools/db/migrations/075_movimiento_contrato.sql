-- 075: movimientos de contrato históricos (insumo para absorción).
--
-- Fuente: SharePoint RAW/"Absorcion Histórica DB.xlsx", hojas jll / viña / curico.
-- Detalle línea a línea de movimientos de arriendo (nuevo contrato, renovación,
-- término) por unidad. No es absorción calculada: es el insumo crudo para
-- derivarla (m2 que entran/salen de ocupación por período), igual que un rent
-- roll lo sería si tuviéramos el histórico completo. Ver [[project-absorcion-historica-manual]].
--
-- activo_key mapeado a dim_activo real (Apo3001/Apo4501/Apo4700/Boulevard/
-- Torre A/Viña Centro/Mall Curicó). tipo_unidad normalizado (capitalización,
-- singular/plural) pero conserva las categorías propias del archivo (incluye
-- 'Estacionamientos' — igual que vacancia, se debe excluir en el cálculo de
-- absorción comercial, no al ingestar).

CREATE TABLE raw_movimiento_contrato (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key              TEXT NOT NULL,
    tipo_unidad             TEXT,
    status                  TEXT,
    arrendatario            TEXT,
    nuevo_arrendatario      TEXT,
    antes_uf                REAL,
    hoy_uf                  REAL,
    antes_uf_m2             REAL,
    hoy_uf_m2               REAL,
    m2                      REAL,
    pct_variacion           REAL,
    vencimiento             TEXT,
    inicio_nuevo_contrato   TEXT,
    nuevo_vencimiento       TEXT,
    comentarios             TEXT,
    source_file             TEXT,
    source_sheet            TEXT,
    source_row              INTEGER,
    file_hash               TEXT,
    ingest_run_id           INTEGER REFERENCES ingest_run(id),
    loaded_at               TEXT DEFAULT (datetime('now')),
    superseded_at           TEXT,
    UNIQUE (file_hash, source_sheet, source_row)
);

CREATE INDEX idx_raw_movimiento_contrato_activo
    ON raw_movimiento_contrato(activo_key);
