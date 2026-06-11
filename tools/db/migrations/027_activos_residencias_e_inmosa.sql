-- Activos individuales de INMOSA (residencias Senior Assist) y edificios
-- residenciales Guardiamarina y Placilla.
--
-- INMOSA existe en dim_activo como activo agregado (activo_key='INMOSA').
-- Aquí se agregan sus 6 residencias individuales, que tienen tasaciones propias.
-- Participación directa de TRI: 43% (vía Inmobiliaria e Inversiones Senior Assist).
--
-- Guardiamarina y Placilla: edificios residenciales incorporados en 2021,
-- 100% propiedad del fondo TRI.

INSERT OR IGNORE INTO dim_activo
    (activo_key, fondo_key, nombre, tipo, participacion, categoria, sociedad)
VALUES
  ('Residencia Arturo Medina',
   'TRI', 'Residencia Arturo Medina', 'residencia', 0.43, 'Residencias',
   'Inmobiliaria e Inversiones Senior Assist Chile S.A.'),
  ('Residencia Candil',
   'TRI', 'Residencia Candil', 'residencia', 0.43, 'Residencias',
   'Inmobiliaria e Inversiones Senior Assist Chile S.A.'),
  ('Residencia Colombia',
   'TRI', 'Residencia Colombia', 'residencia', 0.43, 'Residencias',
   'Inmobiliaria e Inversiones Senior Assist Chile S.A.'),
  ('Residencia Coventry',
   'TRI', 'Residencia Coventry', 'residencia', 0.43, 'Residencias',
   'Inmobiliaria e Inversiones Senior Assist Chile S.A.'),
  ('Residencia Domingo Calderón',
   'TRI', 'Residencia Domingo Calderón', 'residencia', 0.43, 'Residencias',
   'Inmobiliaria e Inversiones Senior Assist Chile S.A.'),
  ('Residencia Padre Errázuriz',
   'TRI', 'Residencia Padre Errázuriz / Leonardo Da Vinci', 'residencia', 0.43, 'Residencias',
   'Inmobiliaria e Inversiones Senior Assist Chile S.A.'),
  ('Ed. Guardiamarina',
   'TRI', 'Edificio Guardiamarina', 'residencial', 1.0, 'Residencias',
   'Ed. Guardiamarina'),
  ('Ed. Placilla',
   'TRI', 'Edificio Placilla', 'residencial', 1.0, 'Residencias',
   'Ed. Placilla');
