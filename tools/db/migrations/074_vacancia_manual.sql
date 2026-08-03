-- 074: vacancia histórica manual + vistas de consolidación.
--
-- Fuente: SharePoint RAW/"Vacancia histórica DB.xlsx" (2017-06 a 2026-12).
-- Cubre los períodos SIN rent roll ingestado. Donde ya existe rent roll
-- (raw_rent_roll_line), la vacancia se calcula directo desde ahí (más
-- granular: incluye tipo_unidad por unidad vía extra_json.tipo_activo_1) y
-- este archivo manual queda solo de respaldo/histórico.
--
-- tipo_unidad NULL = el dato de la fuente ya viene consolidado (no desglosado
-- por tipo). Con valor ('Oficinas'|'Locales Comerciales'|'Bodegas') = desglose
-- por tipo dentro de un activo o complejo.
--
-- activo_key puede ser un activo real de dim_activo (INMOSA, Viña Centro,
-- Mall Curicó, Apo3001, Sucden, Apo4501, Apo4700, Strip Machalí) o el
-- pseudo-key 'PT_consolidado': el archivo fuente no desglosa Parque Titanium
-- por edificio (Torre A / Boulevard) para períodos históricos, solo por tipo
-- de unidad a nivel del complejo completo. Para períodos con rent roll, la
-- vacancia de Torre A/Boulevard por tipo se obtiene de raw_rent_roll_line.

CREATE TABLE raw_vacancia_manual (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activo_key    TEXT NOT NULL,
    tipo_unidad   TEXT,
    periodo       TEXT NOT NULL,
    m2_gla        REAL,
    m2_vacantes   REAL,
    source_file   TEXT,
    source_sheet  TEXT,
    file_hash     TEXT,
    ingest_run_id INTEGER REFERENCES ingest_run(id),
    loaded_at     TEXT DEFAULT (datetime('now')),
    superseded_at TEXT
);

CREATE INDEX idx_raw_vacancia_manual_activo_periodo
    ON raw_vacancia_manual(activo_key, periodo);

-- Vacancia por activo + tipo_unidad, calculada desde rent roll cuando existe
-- (normaliza extra_json.tipo_activo_1 -> tipo_unidad), y desde el archivo
-- manual en el resto de los períodos.
CREATE VIEW v_vacancia_activo_tipo AS
WITH rr AS (
    SELECT
        activo_key,
        periodo,
        -- tipo_activo_1 no sirve para unidades vacantes (queda 'Vacante' en vez
        -- del tipo real); tipo_activo_2 sí es confiable para vacantes y ocupadas.
        CASE json_extract(extra_json, '$.tipo_activo_2')
            WHEN 'Oficina'         THEN 'Oficinas'
            WHEN 'Local'           THEN 'Locales Comerciales'
            WHEN 'Bodega'          THEN 'Bodegas'
            WHEN 'Estacionamiento' THEN 'Estacionamiento'
            ELSE 'Otro'
        END AS tipo_unidad,
        SUM(m2) AS m2_gla,
        SUM(CASE WHEN arrendatario = 'Vacante' THEN m2 ELSE 0 END) AS m2_vacantes
    FROM raw_rent_roll_line
    WHERE superseded_at IS NULL
    GROUP BY activo_key, periodo, tipo_unidad
)
SELECT activo_key, periodo, tipo_unidad, m2_gla, m2_vacantes, 'rent_roll' AS fuente
FROM rr
UNION ALL
SELECT m.activo_key, m.periodo, m.tipo_unidad, m.m2_gla, m.m2_vacantes, 'manual' AS fuente
FROM raw_vacancia_manual m
WHERE m.superseded_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM rr
       WHERE rr.activo_key = m.activo_key AND rr.periodo = m.periodo
  );

-- Vacancia total por activo y período (colapsa tipo_unidad).
-- Excluye 'Estacionamiento': confirmado por el usuario 2026-08-03 (Apo3001
-- 2026-06 GLA rent roll 4589.55 incluye 80 m2 de estacionamientos; excluyéndolos
-- da 4509.55, que calza con el archivo manual ~4509 y con la vacancia exacta
-- 1632.6 == manual). El parking no es parte del universo de vacancia comercial.
--
-- Algunos activos manuales traen tanto un total ya consolidado (tipo_unidad
-- NULL, ej. INMOSA, Fondo Apoquindo hasta 2026-07) como un desglose por tipo
-- (ej. Fondo Apoquindo Oficinas/Locales, que reemplaza al total como fuente
-- vigente desde 2026-08 — el total NULL queda sin valor de vacancia en los
-- periodos nuevos). Otros (PT_consolidado) solo traen el desglose, nunca un
-- total. Regla por columna: usar el total NULL si tiene valor; si no, sumar
-- el desglose (COALESCE independiente para GLA y vacantes, porque pueden
-- venir de filas distintas del archivo fuente en periodos distintos).
CREATE VIEW v_vacancia_activo AS
WITH total_row AS (
    SELECT activo_key, periodo, fuente, m2_gla AS t_gla, m2_vacantes AS t_vac
    FROM v_vacancia_activo_tipo
    WHERE tipo_unidad IS NULL
),
tipo_sum AS (
    SELECT activo_key, periodo, fuente,
           SUM(m2_gla) AS s_gla, SUM(m2_vacantes) AS s_vac
    FROM v_vacancia_activo_tipo
    WHERE tipo_unidad IS NOT NULL AND tipo_unidad != 'Estacionamiento'
    GROUP BY activo_key, periodo, fuente
),
combinado AS (
    SELECT COALESCE(tr.activo_key, ts.activo_key) AS activo_key,
           COALESCE(tr.periodo, ts.periodo) AS periodo,
           COALESCE(tr.fuente, ts.fuente) AS fuente,
           tr.t_gla, tr.t_vac, ts.s_gla, ts.s_vac
    FROM total_row tr
    LEFT JOIN tipo_sum ts
      ON ts.activo_key = tr.activo_key AND ts.periodo = tr.periodo AND ts.fuente = tr.fuente
    UNION
    SELECT COALESCE(tr.activo_key, ts.activo_key), COALESCE(tr.periodo, ts.periodo),
           COALESCE(tr.fuente, ts.fuente), tr.t_gla, tr.t_vac, ts.s_gla, ts.s_vac
    FROM tipo_sum ts
    LEFT JOIN total_row tr
      ON tr.activo_key = ts.activo_key AND tr.periodo = ts.periodo AND tr.fuente = ts.fuente
)
SELECT activo_key, periodo, fuente,
       COALESCE(t_gla, s_gla) AS m2_gla,
       COALESCE(t_vac, s_vac) AS m2_vacantes,
       CAST(COALESCE(t_vac, s_vac) AS REAL) / NULLIF(COALESCE(t_gla, s_gla), 0) AS vacancia_pct
FROM combinado;

-- Vista fondo-efectiva: pondera m2_vacantes por participacion_fondo_activo.
-- Confirmado por el usuario 2026-08-03 para Mall Curicó (participación 0.8):
-- vacancia rent roll 3017.87 * 0.8 = 2414.3, ~coincide con el archivo manual
-- (2476, diff 2.5% dentro de tolerancia). La GLA NO se pondera (el archivo
-- manual reporta la GLA física completa, sin ajustar por participación) —
-- solo el m2 vacante efectivo, para consolidación a nivel fondo.
CREATE VIEW v_vacancia_activo_efectivo AS
SELECT v.activo_key, v.periodo, v.m2_gla, v.m2_vacantes,
       v.m2_vacantes * COALESCE(d.participacion_fondo_activo, 1.0) AS m2_vacantes_efectivo,
       v.vacancia_pct, v.fuente
FROM v_vacancia_activo v
LEFT JOIN dim_activo d ON d.activo_key = v.activo_key;

-- Parque Titanium consolidado (Torre A + Boulevard) por tipo_unidad.
-- Para períodos con rent roll: suma Torre A + Boulevard desglosados por tipo.
-- Para períodos históricos sin rent roll: pasa directo el dato ya
-- consolidado del archivo manual (activo_key = 'PT_consolidado').
CREATE VIEW v_vacancia_pt_consolidado_tipo AS
SELECT periodo, tipo_unidad,
       SUM(m2_gla) AS m2_gla,
       SUM(m2_vacantes) AS m2_vacantes,
       fuente
FROM v_vacancia_activo_tipo
WHERE activo_key IN ('Torre A', 'Boulevard')
GROUP BY periodo, tipo_unidad, fuente
UNION ALL
SELECT periodo, tipo_unidad, m2_gla, m2_vacantes, fuente
FROM v_vacancia_activo_tipo
WHERE activo_key = 'PT_consolidado';

-- Fondo Apoquindo consolidado (Apo4501 + Apo4700) por tipo_unidad.
-- Con rent roll: suma ambos activos desglosados por tipo (Oficinas/Locales/
-- Bodegas/Estacionamiento vía tipo_activo_2). Sin rent roll: usa el desglose
-- manual "Fondo Apoquindo Oficinas/Locales" (solo vacancia, sin GLA por tipo
-- — el archivo fuente no lo trae desglosado históricamente, solo el total).
CREATE VIEW v_vacancia_apoquindo_consolidado_tipo AS
SELECT periodo, tipo_unidad,
       SUM(m2_gla) AS m2_gla,
       SUM(m2_vacantes) AS m2_vacantes,
       fuente
FROM v_vacancia_activo_tipo
WHERE activo_key IN ('Apo4501', 'Apo4700')
GROUP BY periodo, tipo_unidad, fuente
UNION ALL
SELECT periodo, tipo_unidad, m2_gla, m2_vacantes, fuente
FROM v_vacancia_activo_tipo
WHERE activo_key = 'Fondo Apoquindo' AND tipo_unidad IS NOT NULL;
