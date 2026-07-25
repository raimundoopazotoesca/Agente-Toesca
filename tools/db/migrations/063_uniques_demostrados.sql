-- 063: restricciones de unicidad SOLO donde están demostradas.
--
-- Las migraciones históricas declaraban UNIQUE(file_hash, source_row) para las
-- cuatro tablas raw `_line`. Producción nunca lo tuvo, y el análisis mostró que
-- aplicarlo de forma genérica sería incorrecto
-- (docs/analisis-duplicados-dry-run.md §1):
--
--   raw_eeff_line       source_row NULL en el 93% de las filas → la restricción
--                       no impediría nada (SQLite trata cada NULL como distinto).
--                       Su clave real se diseñará tras poblar `seccion` (062).
--   raw_er_activo_line  una fila de la planilla genera una fila POR MES: se
--                       verificó un caso con 104 filas compartiendo
--                       (file_hash, source_row). La restricción rechazaría datos
--                       válidos. Su clave correcta incluye `periodo`, pero hay
--                       10 filas sobrantes que se sanean aparte antes de imponerla.
--   raw_flujo_line      misma estructura, pero 0 sobrantes → se aplica ya.
--   raw_rent_roll_line  source_row siempre presente, 0 sobrantes → se aplica ya.
--
-- Se usan índices únicos (no ALTER TABLE) para no reconstruir las tablas.

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_rent_roll_hash_row
    ON raw_rent_roll_line(file_hash, source_row);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_flujo_hash_row_periodo
    ON raw_flujo_line(file_hash, source_row, periodo);
