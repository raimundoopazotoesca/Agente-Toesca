CREATE TABLE IF NOT EXISTS raw_pagare_intercompania (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    acreedor_fondo    TEXT,
    deudor_sociedad   TEXT,
    tipo              TEXT,
    fecha_inicio      TEXT,
    fecha_vencimiento TEXT,
    monto_uf          REAL,
    tasa              REAL,
    saldo_c_intereses REAL
);
