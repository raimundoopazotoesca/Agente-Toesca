-- Agrega clasificación contable a raw_er_activo_line.
-- seccion      : etiqueta de sección tal como aparece en el EERR (ej. "INGRESOS DE EXPLOTACION")
-- es_operacional: 1 si la cuenta está dentro del bloque operacional (antes de TOTAL OPERACIONAL)

ALTER TABLE raw_er_activo_line ADD COLUMN seccion TEXT;
ALTER TABLE raw_er_activo_line ADD COLUMN es_operacional INTEGER;
