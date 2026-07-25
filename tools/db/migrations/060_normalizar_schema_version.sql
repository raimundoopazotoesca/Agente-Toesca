-- 060: alinear schema_version.applied_at con el resto del esquema.
--
-- Última diferencia entre producción y una DB creada desde el baseline: en
-- producción `applied_at` quedó sin NOT NULL (la tabla la creó schema_v2.sql),
-- mientras que `_ensure_schema_version_table()` la crea con NOT NULL. Sin efecto
-- práctico —el DEFAULT siempre la rellena— pero deja el esquema con un asterisco
-- y el test de paridad no puede afirmar igualdad exacta.
--
-- SQLite no permite añadir NOT NULL a una columna existente: hay que recrear.
-- Son ~60 filas y el runner ejecuta todo en una sola transacción.

CREATE TABLE schema_version_nueva (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO schema_version_nueva (version, applied_at)
SELECT version, COALESCE(applied_at, datetime('now')) FROM schema_version;

DROP TABLE schema_version;

ALTER TABLE schema_version_nueva RENAME TO schema_version;
