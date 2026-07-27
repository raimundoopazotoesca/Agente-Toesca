-- 071: valores fijos editables de Sucden (contrato fijo, sin planilla mensual).
--
-- ingest_er_sucden_fijo.py genera Ingresos/Contribuciones/Sobretasa/Seguros
-- de Sucden sin leer ningún archivo — hasta ahora los 4 montos estaban
-- hardcodeados en el módulo. El usuario pidió poder editarlos por período
-- (input precargado con el valor vigente, editable) y decidir si un cambio
-- es "solo este período" (no toca esta tabla, se pasa como override puntual)
-- o "permanente" (se actualiza acá y aplica desde el próximo período que se
-- ingeste en adelante). El histórico ya persistido en raw_er_activo_line
-- nunca se recalcula a partir de esta tabla.
CREATE TABLE IF NOT EXISTS sucden_valores_fijos (
    cuenta_codigo   TEXT PRIMARY KEY,
    monto_uf        REAL NOT NULL,
    actualizado_at  TEXT DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO sucden_valores_fijos (cuenta_codigo, monto_uf) VALUES
    ('SUCDEN_ING_ARR',   2248.4709),
    ('SUCDEN_CONTRIB',   -326.03266124052874),
    ('SUCDEN_SOBRETASA', -140.0),
    ('SUCDEN_SEG',       0.0);
