-- 085: tipar la renta del rent roll y declarar procedencia de cada fila.
--
-- Confirmado con el usuario 2026-08-28, en el marco de la migración a la
-- planilla única de JLL ("JLL v2").
--
-- PROBLEMA. `renta_uf` guarda hoy una TASA UF/m²/mes, no un total: se lee de la
-- columna "Renta Fija (UF/m2 /mes)" (tools/db/ingest_rent_roll_validated.py:819).
-- El nombre indica lo contrario, y consumidores aguas abajo lo sumaban como si
-- fuera un monto: Apo4501 2026-06 daba 1.384 "UF" sobre 23.110 m² = 0,06 UF/m²,
-- absurdo. Demostrado en docs/rent-roll-renta-semantics-v1.md
-- (script: eval/analysis/audit_renta_uf_semantics.py): `renta_uf × m2` reproduce
-- `extra_json.renta_esperada_total` en el 100% de las filas de Apo4501, Apo4700,
-- Boulevard y Torre A.
--
-- TARGET. `renta_uf` = total UF/mes. `renta_uf_m2` = tasa UF/m²/mes.
--
-- ESTA MIGRACIÓN NO HACE EL BACKFILL. Solo agrega columnas y etiqueta el
-- histórico como 'indeterminada' vía DEFAULT. Ningún valor de `renta_uf` se
-- toca: la reasignación entre campos va en un paso posterior, por período
-- completo, para no violar el invariante de semántica no mixta (ningún
-- (activo_key, periodo) puede tener filas vivas con dos semánticas distintas).

ALTER TABLE raw_rent_roll_line ADD COLUMN renta_uf_m2 REAL;

-- Fecha de corte tal como viene del proveedor, sin truncar. `periodo` sigue
-- siendo el derivado canónico YYYY-MM. JLL v2 mezcla etiquetas de fin de mes
-- (2025-11-30) y de día 1 (2026-07-01) y aún no confirma si significan lo
-- mismo; conservar la fuente permite recorregir la interpretación sin
-- reingestar.
ALTER TABLE raw_rent_roll_line ADD COLUMN fecha_corte_fuente TEXT;

-- Semántica de `renta_uf` en cada fila. El DEFAULT clasifica el histórico sin
-- UPDATE alguno: SQLite lo aplica a las filas existentes al agregar la columna.
-- 'indeterminada' significa "aún no demostrado para esta fila", no "erróneo".
ALTER TABLE raw_rent_roll_line ADD COLUMN renta_semantica TEXT NOT NULL
    DEFAULT 'indeterminada'
    CHECK (renta_semantica IN ('total_uf', 'tasa_uf_m2', 'indeterminada'));

-- Procedencia. El histórico mezcla proveedores (JLL, Tres Asociados y otros,
-- cargados por rutas distintas), así que NO se asigna 'JLL' por default: eso
-- sería inventar procedencia. Nullable a propósito; el backfill determinístico
-- desde ingest_run.tool / source_file va aparte, y lo no derivable queda NULL o
-- 'legacy_unknown'. Para filas nuevas ambas son obligatorias, impuesto en el
-- repo de escritura (no como NOT NULL de tabla, que rompería el histórico).
ALTER TABLE raw_rent_roll_line ADD COLUMN fuente_proveedor TEXT;
ALTER TABLE raw_rent_roll_line ADD COLUMN fuente_formato TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_rr_fuente
    ON raw_rent_roll_line(fuente_proveedor, activo_key, periodo);
