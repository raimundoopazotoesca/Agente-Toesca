-- 090: exponer 'UG' como categoria propia en la taxonomia de vacancia.
--
-- El formato JLL v2 trae una categoria_general 'UG' (123 filas en el archivo del
-- 2026-08-12) que no existia en el rent roll clasico. Su tratamiento esta
-- PENDIENTE de confirmacion con negocio: no se ha decidido si debe excluirse de
-- la GLA rentable como los estacionamientos, o contarse como area arrendable.
--
-- Sin este cambio, 'UG' caeria en el ELSE de la vista ('Otro'), que v_vacancia_
-- activo SI incluye en el universo rentable. Eso seria tomar la decision por
-- omision y ademas dejarla invisible: nadie mirando la vista notaria que hay
-- metros de UG mezclados con 'Otro'.
--
-- Exponerla como categoria propia no decide nada; solo hace la decision
-- visible. Mientras tanto sigue contando en la GLA (mismo comportamiento que
-- 'Otro'), y cuando negocio confirme bastara agregarla a la lista de exclusion
-- de v_vacancia_activo, junto a 'Estacionamiento'.

DROP VIEW IF EXISTS v_vacancia_apoquindo_consolidado_tipo;
DROP VIEW IF EXISTS v_vacancia_pt_consolidado_tipo;
DROP VIEW IF EXISTS v_vacancia_activo_efectivo;
DROP VIEW IF EXISTS v_vacancia_activo;
DROP VIEW IF EXISTS v_vacancia_activo_tipo;

CREATE VIEW v_vacancia_activo_tipo AS
WITH rr AS (
    SELECT activo_key, periodo,
        CASE LOWER(TRIM(json_extract(extra_json, '$.tipo_activo_2')))
            WHEN 'oficina' THEN 'Oficinas'
            WHEN 'local' THEN 'Locales Comerciales'
            WHEN 'bodega' THEN 'Bodegas'
            WHEN 'estacionamiento' THEN 'Estacionamiento'
            WHEN 'parking' THEN 'Estacionamiento'
            WHEN 'ug' THEN 'UG'
            ELSE 'Otro'
        END AS tipo_unidad,
        SUM(m2) AS m2_gla,
        SUM(CASE WHEN LOWER(arrendatario) = 'vacante' THEN m2 ELSE 0 END) AS m2_vacantes
    FROM raw_rent_roll_line WHERE superseded_at IS NULL
    GROUP BY activo_key, periodo, tipo_unidad
)
SELECT activo_key, periodo, tipo_unidad, m2_gla, m2_vacantes, 'rent_roll' AS fuente FROM rr
UNION ALL
SELECT m.activo_key, m.periodo, m.tipo_unidad, m.m2_gla, m.m2_vacantes, 'manual'
FROM raw_vacancia_manual m WHERE m.superseded_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM rr WHERE rr.activo_key=m.activo_key AND rr.periodo=m.periodo);

CREATE VIEW v_vacancia_activo AS
WITH total_row AS (SELECT activo_key,periodo,fuente,m2_gla t_gla,m2_vacantes t_vac FROM v_vacancia_activo_tipo WHERE tipo_unidad IS NULL),
tipo_sum AS (SELECT activo_key,periodo,fuente,SUM(m2_gla) s_gla,SUM(m2_vacantes) s_vac FROM v_vacancia_activo_tipo WHERE tipo_unidad IS NOT NULL AND tipo_unidad!='Estacionamiento' GROUP BY activo_key,periodo,fuente),
combinado AS (
 SELECT COALESCE(tr.activo_key,ts.activo_key) activo_key,COALESCE(tr.periodo,ts.periodo) periodo,COALESCE(tr.fuente,ts.fuente) fuente,tr.t_gla,tr.t_vac,ts.s_gla,ts.s_vac FROM total_row tr LEFT JOIN tipo_sum ts ON ts.activo_key=tr.activo_key AND ts.periodo=tr.periodo AND ts.fuente=tr.fuente
 UNION SELECT COALESCE(tr.activo_key,ts.activo_key),COALESCE(tr.periodo,ts.periodo),COALESCE(tr.fuente,ts.fuente),tr.t_gla,tr.t_vac,ts.s_gla,ts.s_vac FROM tipo_sum ts LEFT JOIN total_row tr ON tr.activo_key=ts.activo_key AND tr.periodo=ts.periodo AND tr.fuente=ts.fuente)
SELECT activo_key,periodo,fuente,COALESCE(t_gla,s_gla) m2_gla,COALESCE(t_vac,s_vac) m2_vacantes,CAST(COALESCE(t_vac,s_vac) AS REAL)/NULLIF(COALESCE(t_gla,s_gla),0) vacancia_pct FROM combinado;

CREATE VIEW v_vacancia_activo_efectivo AS
SELECT v.activo_key,v.periodo,v.m2_gla,v.m2_vacantes,v.m2_vacantes*COALESCE(d.participacion_fondo_activo,1.0) m2_vacantes_efectivo,v.vacancia_pct,v.fuente FROM v_vacancia_activo v LEFT JOIN dim_activo d ON d.activo_key=v.activo_key;
CREATE VIEW v_vacancia_pt_consolidado_tipo AS
SELECT periodo,tipo_unidad,SUM(m2_gla) m2_gla,SUM(m2_vacantes) m2_vacantes,fuente FROM v_vacancia_activo_tipo WHERE activo_key IN ('Torre A','Boulevard') GROUP BY periodo,tipo_unidad,fuente
UNION ALL SELECT periodo,tipo_unidad,m2_gla,m2_vacantes,fuente FROM v_vacancia_activo_tipo WHERE activo_key='PT_consolidado';
CREATE VIEW v_vacancia_apoquindo_consolidado_tipo AS
SELECT periodo,tipo_unidad,SUM(m2_gla) m2_gla,SUM(m2_vacantes) m2_vacantes,fuente FROM v_vacancia_activo_tipo WHERE activo_key IN ('Apo4501','Apo4700') GROUP BY periodo,tipo_unidad,fuente
UNION ALL SELECT periodo,tipo_unidad,m2_gla,m2_vacantes,fuente FROM v_vacancia_activo_tipo WHERE activo_key='Fondo Apoquindo' AND tipo_unidad IS NOT NULL;
