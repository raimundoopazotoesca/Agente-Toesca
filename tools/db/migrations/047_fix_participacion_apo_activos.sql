-- 047_fix_participacion_apo_activos.sql
-- Fix: dim_activo.participacion_fondo_activo para Apo4501/Apo4700 debe ser 1.0.
-- El fondo Apoquindo es dueño 100% de ambos activos. El 30% previo confundía la
-- relación fondo-fondo (TRI→Apo) con la relación fondo-activo.
UPDATE dim_activo
   SET participacion_fondo_activo = 1.0
 WHERE activo_key IN ('Apo4501','Apo4700')
   AND fondo_key = 'Apo';
