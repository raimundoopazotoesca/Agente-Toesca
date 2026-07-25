-- 058: consolidar fondo_key 'APO' -> 'Apo' (clave canónica de dim_fondo).
--
-- Problema: dim_fondo tiene 'Apo', pero 18.009 filas de raw_eeff_line y 15 de
-- raw_valor_cuota_contable quedaron con 'APO'. Eran violaciones de la FK
-- raw_eeff_line.fondo_key -> dim_fondo(fondo_key) que nadie rechazó porque
-- scripts/ingest_eeff.py abre la conexión con sqlite3.connect() sin
-- PRAGMA foreign_keys = ON. Con la conexión de tools/db/connection.py (que sí
-- activa el pragma) cualquier INSERT nuevo con 'APO' falla, de modo que la
-- ingesta EEFF de Apoquindo por web era imposible.
--
-- Alcance deliberadamente acotado al fondo. NO toca:
--   - dim_activo / raw_er_activo_line: 'Apo4501', 'Apo4700', 'Apo3001' ya son
--     claves canónicas, y 'Apo3001' pertenece al fondo TRI, no a Apo.
--   - derived_kpi: las entidades agregadas 'Apoquindo' y 'Fondo Apoquindo' y las
--     claves de nomenclatura larga se resuelven aparte, recalculando desde raw
--     con recetas versionadas (ver docs/matriz-claves-ambiguas-apoquindo.md y
--     ROADMAP F1.9). Reetiquetarlas aquí mezclaría metodologías distintas.
--
-- Reversible: solo reetiqueta, no borra ni fusiona filas. El inverso es
--   UPDATE ... SET fondo_key='APO' WHERE fondo_key='Apo' AND source_file <> 'chatgpt_manual';
-- Backup previo en memory/backups/agente_toesca_v2.pre-apo-consolidacion.db
--
-- Duplicados lógicos que esta migración hace visibles bajo una sola clave (NO
-- se deduplican aquí; la política de qué versión sobrevive es una decisión
-- humana pendiente, ver ROADMAP §8):
--   - raw_eeff_line 2026-03: 'TOTAL ACTIVO' aparece con el mismo monto desde
--     apo_2026Q1.json y desde chatgpt_manual.
--   - raw_valor_cuota_contable: 4 cierres de 2025 (03-31, 06-30, 09-30, 12-31)
--     vienen de apo_2026Q1.json y de cdg_extract.xlsx, con diferencias en el
--     cuarto decimal.
-- Ninguno es nuevo: ya existían y las consultas robustas (UPPER(fondo_key))
-- los veían igual.

-- El runner (tools/db/connection.py::apply_migrations) registra la versión en
-- schema_version dentro de la misma transacción; la migración no debe hacerlo.

UPDATE raw_eeff_line            SET fondo_key = 'Apo' WHERE fondo_key = 'APO';
UPDATE raw_valor_cuota_contable SET fondo_key = 'Apo' WHERE fondo_key = 'APO';
