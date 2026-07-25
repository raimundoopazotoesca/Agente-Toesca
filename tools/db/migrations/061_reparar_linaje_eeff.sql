-- 061: reparar el linaje cruzado de raw_eeff_line y marcar las cargas sin corrida.
--
-- Diagnóstico (docs/analisis-integridad-referencial.md): 2.478 filas tenían el
-- hash del archivo escrito en `ingest_run_id` y `file_hash` vacío — las dos
-- columnas quedaron cruzadas. Verificado con tres comprobaciones: solape del
-- 100% entre filas huérfanas y filas con file_hash NULL; el valor huérfano es un
-- hash de 8 caracteres uniforme; y no existe ningún ingest_run correspondiente
-- (esa tabla solo tiene registros desde 2026-05-25, muy posterior a esas cargas).
--
-- Consecuencia que esto arregla: al no tener file_hash, esas filas eran
-- inalcanzables por mark_superseded() — imposibles de corregir o versionar.
--
-- NO se crean corridas sintéticas: no hay evidencia para reconstruir una corrida
-- real, y una ausencia explícita de trazabilidad es preferible a una trazabilidad
-- artificial. Por eso `ingest_run_id` queda en NULL y se marca el origen con
-- `lineage_status`, que distingue estas filas de las otras 1.044 que ya tenían
-- ingest_run_id NULL por motivos distintos.
--
-- Vocabulario de lineage_status:
--   NULL                 → linaje normal (corrida registrada o hash de archivo)
--   'legacy_untracked'   → carga legacy sin corrida registrada, hash recuperado
--   'manual_sin_archivo' → carga manual sin archivo fuente (identificador sintético)

ALTER TABLE raw_eeff_line ADD COLUMN lineage_status TEXT;

-- ── 1. Mover el hash a su columna y marcar el origen ────────────────────────
UPDATE raw_eeff_line
   SET file_hash      = CAST(ingest_run_id AS TEXT),
       ingest_run_id  = NULL,
       lineage_status = 'legacy_untracked'
 WHERE file_hash IS NULL
   AND ingest_run_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM ingest_run i WHERE i.id = raw_eeff_line.ingest_run_id);

-- ── 2. Identificador sintético para las cargas manuales sin archivo ─────────
-- Formato: manual:<fondo>:<periodo>:<naturaleza>:<fecha de incorporación>.
-- El prefijo 'manual:' deja explícito que NO corresponde a un archivo original,
-- así que nunca puede colisionar con un sha256 real.
-- No se decide precedencia aquí: ambas versiones quedan vigentes hasta validar
-- el documento fuente (ver docs/analisis-duplicados-dry-run.md §3).

UPDATE raw_eeff_line
   SET file_hash      = 'manual:Apo:2020-12:correccion-foto:2026-07-09',
       lineage_status = 'manual_sin_archivo'
 WHERE file_hash IS NULL
   AND source_file LIKE 'EEFF Apo 2020-12 (correccion manual%';

UPDATE raw_eeff_line
   SET file_hash      = 'manual:Apo:2026-03:chatgpt_manual-sin-hash:2026-07-09',
       lineage_status = 'manual_sin_archivo'
 WHERE file_hash IS NULL
   AND source_file = 'chatgpt_manual'
   AND fondo_key = 'Apo'
   AND periodo = '2026-03';
