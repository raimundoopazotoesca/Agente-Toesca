-- 082: ocupación mensual por residencia de INMOSA (Living Acalis).
--
-- Fuente: SharePoint RAW/"Ocupacion Acalis - <mes> <año> - Toesca.xlsx".
-- Una hoja por residencia (9 hoy: Candil, Colombia, Coventry, Errazuriz,
-- Medina, Montahue, Montemar, VA - Cordillera, VA - Valle). INMOSA en
-- dim_activo/raw_er_activo_line es un solo activo agregado (fondo TRI,
-- participación 0.43) sin desglose por residencia — esta tabla agrega esa
-- granularidad fina solo para ocupación, sin tocar el ER/NOI existente.
--
-- dim_residencia: catálogo de residencias, igual patrón que dim_sociedad
-- (holding intermedio entre activo y detalle). camas = capacidad total,
-- viene fijo en cada hoja fuente (fila "Camas"), se actualiza si cambia.
--
-- raw_ocupacion_residencia_line: una fila por (residencia, período) leído de
-- la hoja. ocupacion_pct_fuente = valor crudo del Excel (puede venir >1 o
-- inconsistente con camas/residentes — error de la fuente, se preserva para
-- auditoría). ocupacion_pct = recalculado como cantidad_residentes/camas
-- (decisión del usuario 2026-08-12: no confiar en el % que trae la fuente).
-- Fila "Total" (promedio agregado, no es un período real) se excluye en el
-- parser, nunca llega a esta tabla.

-- vigente_hasta NOT NULL = residencia vendida/fuera del portafolio (mismo
-- patrón que dim_activo.vigente_hasta para Machalí). Se sigue ingestando su
-- histórico para gráficos de ocupación histórica, pero queda excluida de
-- cualquier consolidado "portafolio actual".
CREATE TABLE dim_residencia (
    residencia_key TEXT PRIMARY KEY,
    nombre         TEXT NOT NULL,
    activo_key     TEXT NOT NULL REFERENCES dim_activo(activo_key),
    camas          INTEGER,
    vigente_hasta  TEXT
);

-- Montahue, Montemar, VA - Cordillera, VA - Valle: vendidas, ya no son parte
-- del portafolio (confirmado por el usuario 2026-08-12). vigente_hasta se
-- fija en el ingest = último período con datos en la fuente (proxy de la
-- fecha de venta; ajustar si se conoce la fecha real exacta).

CREATE TABLE raw_ocupacion_residencia_line (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    residencia_key        TEXT NOT NULL REFERENCES dim_residencia(residencia_key),
    periodo               TEXT NOT NULL,
    camas                 INTEGER,
    cantidad_residentes   REAL,
    ocupacion_pct         REAL,
    ocupacion_pct_fuente  REAL,
    ingresos              REAL,
    egresos               REAL,
    fallecimientos        REAL,
    source_file           TEXT,
    source_sheet          TEXT,
    source_row            INTEGER,
    file_hash             TEXT,
    ingest_run_id         INTEGER REFERENCES ingest_run(id),
    loaded_at             TEXT DEFAULT (datetime('now')),
    superseded_at         TEXT,
    UNIQUE(file_hash, residencia_key, source_row)
);

CREATE INDEX idx_raw_ocupacion_residencia_key_periodo
    ON raw_ocupacion_residencia_line(residencia_key, periodo);

-- Ocupación consolidada de INMOSA, 1 fila por período. Incluye TODAS las
-- residencias con datos en ese período (las vendidas dejan de aportar solo
-- porque su serie termina, no se filtran explícitamente) — sirve para el
-- histórico real de ocupación del fondo tal como era en cada momento.
-- ocupacion_pct ponderado por camas (no promedio simple).
CREATE VIEW v_ocupacion_inmosa_consolidado AS
SELECT
    d.activo_key,
    r.periodo,
    SUM(r.camas)               AS camas_total,
    SUM(r.cantidad_residentes) AS residentes_total,
    CAST(SUM(r.cantidad_residentes) AS REAL) / NULLIF(SUM(r.camas), 0) AS ocupacion_pct
FROM raw_ocupacion_residencia_line r
JOIN dim_residencia d ON d.residencia_key = r.residencia_key
WHERE r.superseded_at IS NULL
GROUP BY d.activo_key, r.periodo;

-- Igual, pero solo residencias del portafolio actual (excluye Montahue,
-- Montemar, VA - Cordillera, VA - Valle en TODO el histórico) — para
-- comparar el portafolio vigente contra sí mismo en el tiempo, sin el
-- efecto de discontinuidad al vender una residencia.
CREATE VIEW v_ocupacion_inmosa_vigente AS
SELECT
    d.activo_key,
    r.periodo,
    SUM(r.camas)               AS camas_total,
    SUM(r.cantidad_residentes) AS residentes_total,
    CAST(SUM(r.cantidad_residentes) AS REAL) / NULLIF(SUM(r.camas), 0) AS ocupacion_pct
FROM raw_ocupacion_residencia_line r
JOIN dim_residencia d ON d.residencia_key = r.residencia_key
WHERE r.superseded_at IS NULL
  AND d.vigente_hasta IS NULL
GROUP BY d.activo_key, r.periodo;
