-- 065: estado de validación humana, separado del linaje.
--
-- Por qué se necesita: `lineage_status` responde "de dónde vino el dato"
-- (procedencia), no "alguien verificó que es correcto" (validación). Son ejes
-- independientes: una fila puede tener linaje impecable y no estar verificada, o
-- carecer de archivo fuente y estar confirmada contra los EEFF por una persona.
--
-- El caso que lo motivó: Apo 2020-12 `ESF.total_activo` = 42.343.358.000 existe
-- solo por una carga manual cuya fotografía no está en el repositorio. El usuario
-- la verificó contra los Estados Financieros y confirmó la cifra, pero el archivo
-- original sigue sin estar disponible. Sin este mecanismo, el dato sería
-- indistinguible de uno sin respaldo.
--
-- Mecanismo mínimo, deliberadamente sin sobrediseñar: tres columnas nullable.
-- NULL = no validado explícitamente (el caso normal). No hay máquina de estados
-- ni tabla aparte; si más adelante hace falta historial de validaciones, se
-- modela entonces con evidencia de que se necesita.

ALTER TABLE raw_eeff_line ADD COLUMN validado_por TEXT;
ALTER TABLE raw_eeff_line ADD COLUMN validado_at TEXT;
ALTER TABLE raw_eeff_line ADD COLUMN validacion_fuente TEXT;

-- ── Apo 2020-12: registrar la validación confirmada por el usuario ──────────
-- Las tres cifras fueron verificadas contra los Estados Financieros:
--   activo corriente      405.468.000
--   activo no corriente   41.937.890.000
--   total activo          42.343.358.000   (cuadra exacto con la suma)
-- Se marcan las filas que quedan vigentes para esas tres cuentas.

UPDATE raw_eeff_line
   SET validado_por      = 'usuario',
       validado_at       = '2026-07-24',
       validacion_fuente = 'Estados Financieros Apo 2020-12 (confirmado por el usuario; '
                           || 'la fotografía original no está en el repositorio)'
 WHERE fondo_key = 'Apo'
   AND periodo   = '2020-12'
   AND cuenta_codigo_canonical IN (
        'ESF.total_activo', 'ESF.total_activo_corriente', 'ESF.total_activo_no_corriente')
   AND superseded_at IS NULL;

-- ── Resolver los dos solapados según la política de versionado ──────────────
-- Caso 2 (misma clave de negocio, MISMOS valores, distinto archivo): sobrevive la
-- versión con mejor linaje. Las filas del JSON `EEFF_APO_202103.json` tienen
-- file_hash real de un documento y son la primera ingesta; las manuales tienen
-- identificador sintético. Los valores son idénticos al dígito, así que la
-- elección no altera ninguna cifra.
--
-- `ESF.total_activo` NO se toca: la fila manual es la única que aporta ese total
-- para el período y queda vigente.

UPDATE raw_eeff_line
   SET superseded_at = datetime('now')
 WHERE fondo_key = 'Apo'
   AND periodo   = '2020-12'
   AND cuenta_codigo_canonical IN ('ESF.total_activo_corriente', 'ESF.total_activo_no_corriente')
   AND lineage_status = 'manual_sin_archivo'
   AND superseded_at IS NULL;
