-- 067: índices únicos PARCIALES sobre las filas vigentes.
--
-- Problema con la forma anterior. Un índice único total sobre la clave de
-- negocio impide reingerir un archivo después de supersederlo: la fila
-- superseded sigue ocupando la clave. Y la salida "obvia" —agregar
-- `superseded_at` como una columna más del UNIQUE, que es lo que hacen las
-- tablas de parking— NO funciona: SQLite considera cada NULL distinto de
-- cualquier otro, así que `UNIQUE(..., superseded_at)` deja convivir N filas
-- vigentes con la misma clave.
--
-- Verificado en una DB limpia: dos INSERT en raw_parking_ingreso_line con la
-- misma (activo_key, periodo, concepto_id) y superseded_at NULL fueron ACEPTADOS
-- por el UNIQUE inline. Esas cuatro restricciones eran decorativas.
--
-- La forma correcta es un índice único parcial con WHERE superseded_at IS NULL:
--   · una sola versión vigente por clave de negocio
--   · cualquier cantidad de versiones superseded conservadas
--   · reingesta posible tras superseder, sin depender de que el archivo
--     corregido tenga un hash distinto
--   · auditoría histórica intacta
--
-- Los UNIQUE inline de parking están en el CREATE TABLE y quitarlos exigiría
-- recrear cuatro tablas. Como el índice parcial ya aporta la garantía real, se
-- dejan como restricción vestigial: no protegen nada, pero tampoco estorban.
-- Queda anotado en el ROADMAP como deuda menor.

DROP INDEX IF EXISTS uq_raw_er_activo_hash_row_periodo_activo;
DROP INDEX IF EXISTS uq_raw_rent_roll_hash_row;
DROP INDEX IF EXISTS uq_raw_flujo_hash_row_periodo;

-- ── Tablas raw de línea ─────────────────────────────────────────────────────
-- Claves ya validadas contra los datos (ver docs/analisis-saneamiento-fase2.md):
-- er_activo incluye activo_key porque una fila de origen puede repartirse entre
-- activos (split 75/25 de contribuciones); flujo incluye periodo porque las
-- planillas traen los meses en columnas.

CREATE UNIQUE INDEX IF NOT EXISTS uq_er_activo_vivo
    ON raw_er_activo_line (file_hash, source_row, periodo, activo_key)
 WHERE superseded_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_rent_roll_vivo
    ON raw_rent_roll_line (file_hash, source_row)
 WHERE superseded_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_flujo_vivo
    ON raw_flujo_line (file_hash, source_row, periodo)
 WHERE superseded_at IS NULL;

-- ── Parking: la garantía que el UNIQUE inline nunca dio ─────────────────────

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
