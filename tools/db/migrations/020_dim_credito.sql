CREATE TABLE IF NOT EXISTS dim_credito (
    credito_key         TEXT PRIMARY KEY,
    activo_key          TEXT NOT NULL,
    fondo_key           TEXT NOT NULL,
    sociedad            TEXT,
    acreedor            TEXT,
    tipo_deuda          TEXT,
    part_fondo          REAL,
    deuda_inicial_uf    REAL,
    tasa_anual          REAL,
    cuota_mensual_uf    REAL,
    fecha_inicio        TEXT,
    fecha_vencimiento   TEXT,
    estado              TEXT DEFAULT 'VIGENTE',
    encargado           TEXT,
    perfil_amortizacion TEXT
);
