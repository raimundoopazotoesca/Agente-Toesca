-- Consolidación histórica del parking Parque Titanium (SABA).
-- Ver docs/superpowers/specs/2026-07-23-parking-pt-consolidacion-design.md
--
-- dim_activo no tiene columna id (usa activo_key TEXT PRIMARY KEY) y no existe
-- una fila a nivel de complejo (solo 'Torre A' y 'Boulevard' bajo fondo PT).
-- El parking es un servicio del complejo completo, no de una torre puntual,
-- así que se agrega una fila propia en dim_activo para referenciarlo.
INSERT INTO dim_activo (activo_key, fondo_key, nombre, tipo, participacion_fondo_activo, categoria)
VALUES ('Parking PT', 'PT', 'Parking Parque Titanium (SABA)', 'parking', 1.0, 'Parking');

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

-- Ventas
INSERT INTO dim_concepto_parking (codigo, nombre, tipo, signo) VALUES
  ('70500000-254', 'Ingresos Efectivos (Neto)', 'venta', 1),
  ('70500001-256', 'Facturas Pre pago', 'venta', 1),
  ('70500002-261', 'Ingresos Empresas (Neto)', 'venta', 1),
  ('70500002-261', 'Notas de credito', 'venta', -1),
  ('70500002-261', 'Facturas Post pago', 'venta', 1),
  ('70500003-250', 'Abonados (Neto)', 'venta', 1),
  ('70500003-250', 'Notas de credito', 'venta', -1);

-- Gastos (nombres exactos como vienen en la planilla, con tildes -- deben
-- calzar carácter a carácter con lo que lee openpyxl o el script de ingesta
-- crea conceptos duplicados vía get_or_create_concepto)
INSERT INTO dim_concepto_parking (codigo, nombre, tipo, signo) VALUES
  ('363', 'MANTENCION SKYDATA 44 UF TITANIUM', 'gasto', -1),
  ('253', 'ADM. ESTACIONAMIENTOS TITANIUM', 'gasto', -1),
  ('200', 'Otros gastos', 'gasto', -1),
  ('200', 'Tarifario', 'gasto', -1),
  ('363', 'Horas extra', 'gasto', -1),
  ('200', 'Facturación electronica 44,5 UF', 'gasto', -1),
  ('363', 'Repuestos mantención', 'gasto', -1),
  ('200', 'Licencia y habilitación transbank', 'gasto', -1),
  ('363', 'Comisión vtas Transbank', 'gasto', -1),
  ('363', 'Diferencia Comisión vtas Transbank', 'gasto', -1),
  ('363', 'Comisión por ventas', 'gasto', -1),
  (NULL, 'Ticket', 'gasto', -1),
  (NULL, 'Otras mantenciones', 'gasto', -1);

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
  superseded_at  TEXT,
  UNIQUE(activo_key, fecha, superseded_at)
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
