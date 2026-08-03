-- 077: fix bug case-sensitive en detección de unidades vacantes.
--
-- v_vacancia_activo_tipo filtraba `arrendatario = 'Vacante'`, pero el rent
-- roll trae tanto 'Vacante' como 'vacante' (minúscula) como valores válidos
-- de arrendatario para unidades vacías. Las unidades en minúscula quedaban
-- fuera de m2_vacantes (contadas como GLA, no como vacancia).
--
-- Detectado 2026-08-03 comparando Apo4501 jun-2026 contra el usuario: vacancia
-- Oficinas+Locales daba 560,61 m2 (bug) vs 1.507,57 m2 esperado. Con
-- LOWER(arrendatario)='vacante' se recuperan 961,96 m2 de Apo4501 (19
-- unidades) y 2,0 m2 de Apo4700 (2 unidades) que estaban mal contados como
-- ocupados.
--
-- Recrea las 5 vistas de la cadena (todas dependen de v_vacancia_activo_tipo)
-- porque SQLite no permite ALTER VIEW.

DROP VIEW IF EXISTS v_vacancia_apoquindo_consolidado_tipo;
DROP VIEW IF EXISTS v_vacancia_pt_consolidado_tipo;
DROP VIEW IF EXISTS v_vacancia_activo_efectivo;
DROP VIEW IF EXISTS v_vacancia_activo;
DROP VIEW IF EXISTS v_vacancia_activo_tipo;

CREATE VIEW v_vacancia_activo_tipo AS
WITH rr AS (
    SELECT
        activo_key,
        periodo,
        CASE json_extract(extra_json, '$.tipo_activo_2')
            WHEN 'Oficina'         THEN 'Oficinas'
            WHEN 'Local'           THEN 'Locales Comerciales'
            WHEN 'Bodega'          THEN 'Bodegas'
            WHEN 'Estacionamiento' THEN 'Estacionamiento'
            ELSE 'Otro'
        END AS tipo_unidad,
        SUM(m2) AS m2_gla,
        SUM(CASE WHEN LOWER(arrendatario) = 'vacante' THEN m2 ELSE 0 END) AS m2_vacantes
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

CREATE VIEW v_vacancia_activo_efectivo AS
SELECT v.activo_key, v.periodo, v.m2_gla, v.m2_vacantes,
       v.m2_vacantes * COALESCE(d.participacion_fondo_activo, 1.0) AS m2_vacantes_efectivo,
       v.vacancia_pct, v.fuente
FROM v_vacancia_activo v
LEFT JOIN dim_activo d ON d.activo_key = v.activo_key;

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
