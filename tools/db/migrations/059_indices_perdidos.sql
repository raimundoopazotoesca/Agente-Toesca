-- 059: recuperar los índices que las migraciones declaraban pero producción nunca tuvo.
--
-- Las versiones 1–22 se marcaron aplicadas en un solo lote (2026-06-01 17:15:10)
-- sin ejecutarse: la DB se bootstrapeó desde tools/db/schema_v2.sql. Por eso
-- faltan en producción los 8 índices de `010_add_performance_indexes.sql` y
-- otros 4 de las migraciones iniciales, aunque `schema_version` los diera por
-- aplicados.
--
-- Son puramente aditivos: no cambian datos ni imponen restricciones. Se aplican
-- aquí para que producción y el baseline (060) queden idénticos y para que
-- `schema_version` deje de mentir sobre estas versiones.
--
-- NO se incluyen aquí los `UNIQUE(file_hash, source_row)` de las 4 tablas raw
-- `_line`, que esas mismas migraciones también declaraban: imponerlos hoy
-- fallaría porque existen duplicados vivos. Van después del saneamiento
-- (ROADMAP F0.4), aplicados a producción y al baseline a la vez.

CREATE INDEX IF NOT EXISTS idx_dim_activo_fondo      ON dim_activo(fondo_key);
CREATE INDEX IF NOT EXISTS idx_dim_serie_fondo       ON dim_serie(fondo_key);
CREATE INDEX IF NOT EXISTS idx_ingest_run_hash       ON ingest_run(file_hash);

CREATE INDEX IF NOT EXISTS idx_raw_eeff_hash         ON raw_eeff_line(file_hash);
CREATE INDEX IF NOT EXISTS idx_raw_eeff_periodo      ON raw_eeff_line(periodo);
CREATE INDEX IF NOT EXISTS idx_raw_eeff_cuenta       ON raw_eeff_line(cuenta_codigo);

CREATE INDEX IF NOT EXISTS idx_raw_er_activo_hash    ON raw_er_activo_line(file_hash);
CREATE INDEX IF NOT EXISTS idx_raw_er_periodo        ON raw_er_activo_line(periodo);
CREATE INDEX IF NOT EXISTS idx_raw_er_cuenta         ON raw_er_activo_line(cuenta_codigo);
CREATE INDEX IF NOT EXISTS idx_raw_er_activo_noi     ON raw_er_activo_line(activo_key, periodo, es_operacional);

CREATE INDEX IF NOT EXISTS idx_raw_flujo_hash        ON raw_flujo_line(file_hash);
CREATE INDEX IF NOT EXISTS idx_raw_rr_hash           ON raw_rent_roll_line(file_hash);
