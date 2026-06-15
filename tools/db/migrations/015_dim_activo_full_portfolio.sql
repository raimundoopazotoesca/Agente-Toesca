-- Expansión dim_activo al portfolio completo según organigrama oficial Toesca.
--
-- Estructura societaria:
--   TRI (fondo madre)
--     ├─ 100% → Inmobiliaria Chañarcillo Ltda → 68,5%
--     │         ├─ Bodegas Maipú (Sucden)     → activo_key='Sucden'
--     │         └─ Apoquindo 3001              → activo_key='Apo3001'
--     ├─ 100% → Inmobiliaria VC SpA → Inmobiliaria Viña Centro SpA
--     │         └─ Mall Paseo Viña Centro      → activo_key='Viña Centro'
--     ├─ 80%  → Power Center Curicó SpA
--     │         └─ Power Center Paseo Curicó   → activo_key='Mall Curicó'
--     ├─ 43%  → Inmobiliaria e Inv. Senior Assist Chile S.A.
--     │         └─ 6 Residencias Adulto Mayor  → activo_key='INMOSA'
--     ├─ 33,3% → Fondo PT
--     │          ├─ Torre A.S.A.               → activo_key='PT' (agregado), 'Torre A' (detalle)
--     │          └─ Inmob. Boulevard PT SpA    → activo_key='Boulevard' (detalle)
--     └─ 30%  → Fondo Apo → Inmobiliaria Apoquindo SpA
--               ├─ Apoquindo 4501              → activo_key='Apo4501'
--               └─ Apoquindo 4700              → activo_key='Apo4700'
--
-- participacion = participación efectiva de TRI en el activo (para ponderación).
-- Los activos agregados 'PT' y 'Apoquindo' se mantienen por retrocompatibilidad
-- (raw_rent_roll_line, derived_kpi los referencian).

ALTER TABLE dim_activo ADD COLUMN sociedad TEXT;

-- Corregir Sucden: participacion era 1.0, debe ser 0.685 (vía Chañarcillo)
UPDATE dim_activo
   SET participacion = 0.685,
       nombre        = 'Bodegas Maipú (Sucden)',
       sociedad      = 'Inmobiliaria Chañarcillo Ltda'
 WHERE activo_key = 'Sucden';

-- Actualizar sociedades y nombres de activos existentes
UPDATE dim_activo
   SET sociedad = 'Inmobiliaria e Inversiones Senior Assist Chile S.A.'
 WHERE activo_key = 'INMOSA';

UPDATE dim_activo
   SET nombre   = 'Parque Titanium (Torre A + Boulevard)',
       sociedad = 'Torre A.S.A. e Inmob. Boulevard PT SpA'
 WHERE activo_key = 'PT';

UPDATE dim_activo
   SET sociedad = 'Inmobiliaria Viña Centro SpA'
 WHERE activo_key = 'Viña Centro';

UPDATE dim_activo
   SET sociedad = 'Power Center Curicó SpA'
 WHERE activo_key = 'Mall Curicó';

UPDATE dim_activo
   SET sociedad = 'Inmobiliaria Chañarcillo Ltda'
 WHERE activo_key = 'Apo3001';

UPDATE dim_activo
   SET nombre   = 'Apoquindo 4501 y 4700',
       sociedad = 'Inmobiliaria Apoquindo SpA'
 WHERE activo_key = 'Apoquindo';

-- Agregar activos faltantes (detalle por edificio)
INSERT OR IGNORE INTO dim_activo
    (activo_key, fondo_key, nombre, tipo, participacion, categoria, sociedad)
VALUES
  ('Torre A',   'PT',  'Torre A',          'oficina',  0.333, 'Oficinas', 'Torre A.S.A.'),
  ('Boulevard', 'PT',  'Boulevard PT',     'oficina',  0.333, 'Oficinas', 'Inmobiliaria Boulevard PT SpA'),
  ('Apo4501',   'Apo', 'Apoquindo 4501',   'oficina',  0.300, 'Oficinas', 'Inmobiliaria Apoquindo SpA'),
  ('Apo4700',   'Apo', 'Apoquindo 4700',   'oficina',  0.300, 'Oficinas', 'Inmobiliaria Apoquindo SpA');
