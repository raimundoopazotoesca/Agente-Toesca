-- 062: columna `seccion` en raw_eeff_line.
--
-- Problema que resuelve: raw_eeff_line no tiene forma de distinguir dos partidas
-- homónimas del mismo estado. Hoy hay 147 grupos con el nombre 'Total' y 102 con
-- 'Otros' repetidos dentro del mismo archivo y período, con montos distintos —
-- son partidas diferentes, no duplicados, pero la DB no puede separarlas: el 82%
-- de las filas no tiene cuenta_codigo_canonical y source_row es NULL en el 93%.
-- (docs/analisis-duplicados-dry-run.md §4.)
--
-- `raw_er_activo_line` ya tiene esta columna; raw_eeff_line se alinea.
--
-- Reglas:
--   - Nullable: el histórico sin sección demostrable se queda en NULL. NO se
--     inventa una sección para filas donde no pueda probarse desde el documento
--     o la metadata original.
--   - Obligatoria en ingestas nuevas cuando la fuente permita identificarla.
--   - `seccion` usa vocabulario normalizado; `seccion_original` conserva la
--     denominación literal del documento cuando es más específica (p. ej.
--     "Nota 14 - Ingresos por arriendo").
--
-- Vocabulario normalizado de `seccion`:
--   ESF   Estado de Situación Financiera (balance)
--   ER    Estado de Resultados
--   EFE   Estado de Flujos de Efectivo
--   ECP   Estado de Cambios en el Patrimonio
--   NOTA  Notas a los estados financieros
--   OTRO  identificable pero fuera de las anteriores
--
-- La clave única parcial de raw_eeff_line se diseñará DESPUÉS de poblar esta
-- columna y de validar la granularidad real necesaria: una misma cuenta puede
-- aparecer en estados, contextos, series o acumulados distintos.

ALTER TABLE raw_eeff_line ADD COLUMN seccion TEXT;
ALTER TABLE raw_eeff_line ADD COLUMN seccion_original TEXT;

-- Backfill acotado y demostrable: el prefijo del código canónico identifica el
-- estado sin ambigüedad (los códigos se asignaron por sección al mapear).
-- Solo se tocan filas con canónico; el resto queda NULL a propósito.
UPDATE raw_eeff_line SET seccion = 'ESF'
 WHERE seccion IS NULL AND cuenta_codigo_canonical LIKE 'ESF.%';

UPDATE raw_eeff_line SET seccion = 'ER'
 WHERE seccion IS NULL AND cuenta_codigo_canonical LIKE 'ER.%';

UPDATE raw_eeff_line SET seccion = 'EFE'
 WHERE seccion IS NULL AND cuenta_codigo_canonical LIKE 'EFE.%';

UPDATE raw_eeff_line SET seccion = 'ECP'
 WHERE seccion IS NULL AND cuenta_codigo_canonical LIKE 'ECP.%';

CREATE INDEX IF NOT EXISTS idx_raw_eeff_seccion ON raw_eeff_line(seccion);
