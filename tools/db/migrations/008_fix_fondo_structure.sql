-- Corrección de estructura de fondos según organigrama oficial (2026-05-25).
--
-- Fondo madre: Toesca Rentas Inmobiliarias Fondo de Inversión (A&R Rentas).
-- Apo3001 pertenece al fondo madre vía Inmobiliaria Chañarcillo Ltda (100%),
-- que a su vez tiene 68,5% de participación en Apoquindo 3001.
-- Machalí ya no forma parte del portfolio (excluido).
--
-- Correcciones:
--   Apo3001: fondo_key A&R Apoquindo → A&R Rentas, participacion 1.0 → 0.685
--   Nombres de fondos actualizados al nombre oficial del organigrama.

UPDATE dim_activo
   SET fondo_key     = 'A&R Rentas',
       participacion = 0.685,
       nombre        = 'Apoquindo 3001'
 WHERE activo_key = 'Apo3001';

-- Nombres oficiales de los fondos (organigrama Toesca Rentas Inmobiliarias).
UPDATE dim_fondo SET nombre = 'Toesca Rentas Inmobiliarias Fondo de Inversión'
 WHERE fondo_key = 'A&R Rentas';
UPDATE dim_fondo SET nombre = 'Fondo Toesca Rentas Inmobiliarias PT'
 WHERE fondo_key = 'A&R PT';
UPDATE dim_fondo SET nombre = 'Fondo Toesca Rentas Inmob Apoquindo'
 WHERE fondo_key = 'A&R Apoquindo';
