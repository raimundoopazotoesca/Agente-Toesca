-- 068: quitar el UNIQUE inline de las 4 tablas de parking.
--
-- La migración 067 les agregó índices únicos parciales, que sí garantizan una
-- sola fila vigente por clave. Se pensó dejar el UNIQUE inline como restricción
-- vestigial inofensiva, pero los tests demostraron que **estorba**:
--
--   UNIQUE(activo_key, periodo, concepto_id, superseded_at)
--
-- rechaza dos filas anuladas en el mismo segundo, porque `datetime('now')` tiene
-- resolución de segundos y ambas quedarían con idéntico superseded_at. Es decir,
-- impide conservar el historial cuando se supersede dos veces seguidas — justo
-- el escenario de reingesta que el índice parcial venía a habilitar.
--
-- Como el UNIQUE está en el CREATE TABLE, quitarlo exige recrear la tabla
-- (procedimiento de 12 pasos de SQLite). Son tablas chicas (174 a 1.277 filas).
-- Los índices parciales de 067 se recrean al final, ya que DROP TABLE los borra.
--
-- Se preserva el esquema exacto, incluidas las FK y los DEFAULT.

PRAGMA foreign_keys = OFF;

-- Las 5 vistas de parking referencian estas tablas: SQLite invalida el esquema
-- al hacer DROP TABLE con vistas dependientes. Se eliminan y se recrean al final,
-- idénticas (se conserva su DDL literal).
DROP VIEW IF EXISTS v_parking_resultado_uf;
DROP VIEW IF EXISTS v_parking_ocupacion_mensual;
DROP VIEW IF EXISTS v_parking_ocupacion_diaria;
DROP VIEW IF EXISTS v_parking_ratio_no_abonados;
DROP VIEW IF EXISTS v_parking_mensual;

-- ── raw_parking_ingreso_line ────────────────────────────────────────────────
CREATE TABLE raw_parking_ingreso_line_nueva (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
  periodo        TEXT NOT NULL,
  concepto_id    INTEGER NOT NULL REFERENCES dim_concepto_parking(id),
  monto_clp      REAL NOT NULL,
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT
);
INSERT INTO raw_parking_ingreso_line_nueva
  (id, activo_key, periodo, concepto_id, monto_clp, source_file, file_hash,
   ingest_run_id, loaded_at, superseded_at)
SELECT id, activo_key, periodo, concepto_id, monto_clp, source_file, file_hash,
       ingest_run_id, loaded_at, superseded_at FROM raw_parking_ingreso_line;
DROP TABLE raw_parking_ingreso_line;
ALTER TABLE raw_parking_ingreso_line_nueva RENAME TO raw_parking_ingreso_line;

-- ── raw_parking_gasto_line ──────────────────────────────────────────────────
CREATE TABLE raw_parking_gasto_line_nueva (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
  periodo        TEXT NOT NULL,
  concepto_id    INTEGER NOT NULL REFERENCES dim_concepto_parking(id),
  monto_clp      REAL NOT NULL,
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT
);
INSERT INTO raw_parking_gasto_line_nueva
  (id, activo_key, periodo, concepto_id, monto_clp, source_file, file_hash,
   ingest_run_id, loaded_at, superseded_at)
SELECT id, activo_key, periodo, concepto_id, monto_clp, source_file, file_hash,
       ingest_run_id, loaded_at, superseded_at FROM raw_parking_gasto_line;
DROP TABLE raw_parking_gasto_line;
ALTER TABLE raw_parking_gasto_line_nueva RENAME TO raw_parking_gasto_line;

-- ── raw_parking_facturacion_line ────────────────────────────────────────────
CREATE TABLE raw_parking_facturacion_line_nueva (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
  periodo        TEXT NOT NULL,
  concepto       TEXT NOT NULL,
  monto_clp      REAL NOT NULL,
  source_file    TEXT,
  file_hash      TEXT,
  ingest_run_id  INTEGER REFERENCES ingest_run(id),
  loaded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at  TEXT
);
INSERT INTO raw_parking_facturacion_line_nueva
  (id, activo_key, periodo, concepto, monto_clp, source_file, file_hash,
   ingest_run_id, loaded_at, superseded_at)
SELECT id, activo_key, periodo, concepto, monto_clp, source_file, file_hash,
       ingest_run_id, loaded_at, superseded_at FROM raw_parking_facturacion_line;
DROP TABLE raw_parking_facturacion_line;
ALTER TABLE raw_parking_facturacion_line_nueva RENAME TO raw_parking_facturacion_line;

-- ── raw_parking_ticket_line ─────────────────────────────────────────────────
CREATE TABLE raw_parking_ticket_line_nueva (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  activo_key       TEXT NOT NULL REFERENCES dim_activo(activo_key),
  fecha            TEXT NOT NULL,
  tickets          INTEGER NOT NULL,
  feriado          INTEGER NOT NULL DEFAULT 0,
  source_file      TEXT,
  file_hash        TEXT,
  ingest_run_id    INTEGER REFERENCES ingest_run(id),
  loaded_at        TEXT NOT NULL DEFAULT (datetime('now')),
  superseded_at    TEXT,
  monto_bruto_clp  REAL
);
INSERT INTO raw_parking_ticket_line_nueva
  (id, activo_key, fecha, tickets, feriado, source_file, file_hash,
   ingest_run_id, loaded_at, superseded_at, monto_bruto_clp)
SELECT id, activo_key, fecha, tickets, feriado, source_file, file_hash,
       ingest_run_id, loaded_at, superseded_at, monto_bruto_clp FROM raw_parking_ticket_line;
DROP TABLE raw_parking_ticket_line;
ALTER TABLE raw_parking_ticket_line_nueva RENAME TO raw_parking_ticket_line;

-- ── Recrear los índices parciales (DROP TABLE se los llevó) ─────────────────
CREATE UNIQUE INDEX IF NOT EXISTS uq_parking_ingreso_vivo
    ON raw_parking_ingreso_line (activo_key, periodo, concepto_id)
 WHERE superseded_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_parking_gasto_vivo
    ON raw_parking_gasto_line (activo_key, periodo, concepto_id)
 WHERE superseded_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_parking_facturacion_vivo
    ON raw_parking_facturacion_line (activo_key, periodo, concepto)
 WHERE superseded_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_parking_ticket_vivo
    ON raw_parking_ticket_line (activo_key, fecha)
 WHERE superseded_at IS NULL;

-- ── Recrear las vistas, idénticas ──────────────────────────────────────────
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
CREATE VIEW v_parking_ocupacion_diaria AS
SELECT
  t.activo_key,
  t.fecha,
  substr(t.fecha, 1, 7) AS periodo,
  t.tickets,
  t.feriado,
  t.monto_bruto_clp,
  r.estacionamientos_no_abonados,
  t.monto_bruto_clp / 40.0 AS tiempo_total_min,
  8 * 60 * r.estacionamientos_no_abonados AS tiempo_disponible_min,
  (t.monto_bruto_clp / 40.0) / (8 * 60 * r.estacionamientos_no_abonados) AS ocupacion_diaria
FROM raw_parking_ticket_line t
CROSS JOIN v_parking_ratio_no_abonados r
WHERE t.superseded_at IS NULL;
CREATE VIEW v_parking_ocupacion_mensual AS
SELECT
  activo_key,
  periodo,
  COUNT(*) AS dias,
  SUM(tickets) AS tickets_mes,
  SUM(monto_bruto_clp) AS bruto_mes,
  SUM(tiempo_total_min) AS tiempo_total_min_mes,
  SUM(tiempo_disponible_min) AS tiempo_disponible_min_mes,
  SUM(tiempo_total_min) / SUM(tiempo_disponible_min) AS ocupacion_mensual
FROM v_parking_ocupacion_diaria
GROUP BY activo_key, periodo;
CREATE VIEW v_parking_ratio_no_abonados AS
WITH ult12 AS (
  SELECT DISTINCT periodo FROM raw_parking_ingreso_line
  WHERE activo_key = 'Parking PT'
  ORDER BY periodo DESC LIMIT 12
),
tot AS (
  SELECT
    SUM(CASE WHEN c.codigo != '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_variables_u12m,
    SUM(i.monto_clp) AS ingresos_totales_u12m
  FROM raw_parking_ingreso_line i
  JOIN dim_concepto_parking c ON c.id = i.concepto_id
  WHERE i.activo_key = 'Parking PT' AND i.superseded_at IS NULL
    AND i.periodo IN (SELECT periodo FROM ult12)
)
SELECT
  ingresos_variables_u12m,
  ingresos_totales_u12m,
  CAST(ingresos_variables_u12m AS REAL) / ingresos_totales_u12m AS ratio_variable,
  (CAST(ingresos_variables_u12m AS REAL) / ingresos_totales_u12m) * 502 AS estacionamientos_no_abonados
FROM tot;
CREATE VIEW v_parking_resultado_uf AS
WITH mensual AS (
  SELECT
    i.periodo,
    SUM(i.monto_clp) AS ingresos_netos_clp,
    SUM(CASE WHEN c.codigo != '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_variables_clp,
    SUM(CASE WHEN c.codigo = '70500003-250' THEN i.monto_clp ELSE 0 END) AS ingresos_abonados_clp
  FROM raw_parking_ingreso_line i
  JOIN dim_concepto_parking c ON c.id = i.concepto_id
  WHERE i.activo_key = 'Parking PT' AND i.superseded_at IS NULL
  GROUP BY i.periodo
),
gastos AS (
  SELECT periodo, SUM(monto_clp) AS gastos_netos_clp
  FROM raw_parking_gasto_line
  WHERE activo_key = 'Parking PT' AND superseded_at IS NULL
  GROUP BY periodo
),
uf_ult_dia AS (
  SELECT substr(fecha, 1, 7) AS periodo, MAX(fecha) AS last_fecha
  FROM raw_uf_diaria
  GROUP BY substr(fecha, 1, 7)
),
uf_mes AS (
  SELECT ud.periodo, u.valor AS uf_valor
  FROM uf_ult_dia ud
  JOIN raw_uf_diaria u ON u.fecha = ud.last_fecha
)
SELECT
  m.periodo,
  m.ingresos_netos_clp,
  g.gastos_netos_clp,
  m.ingresos_netos_clp - g.gastos_netos_clp AS resultado_neto_clp,
  u.uf_valor,
  (m.ingresos_netos_clp - g.gastos_netos_clp) / u.uf_valor AS resultado_neto_uf,
  m.ingresos_variables_clp / u.uf_valor AS ingresos_variables_uf,
  m.ingresos_abonados_clp / u.uf_valor AS ingresos_abonados_uf
FROM mensual m
JOIN gastos g ON g.periodo = m.periodo
JOIN uf_mes u ON u.periodo = m.periodo;

PRAGMA foreign_keys = ON;
