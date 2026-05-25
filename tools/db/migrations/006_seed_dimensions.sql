-- Seeds de dimensiones desde catálogos hardcoded en código.
-- INSERT OR IGNORE para que la migración sea segura ante reaplicaciones manuales.

INSERT OR IGNORE INTO dim_fondo (fondo_key, nombre, sharepoint_folder) VALUES
  ('Apo', 'Fondo Toesca Rentas Inmob Apoquindo',              'Fondos\Rentas Apoquindo'),
  ('PT',        'Fondo Toesca Rentas Inmobiliarias PT',              'Fondos\Rentas PT'),
  ('TRI',    'Toesca Rentas Inmobiliarias Fondo de Inversión',    'Fondos\Rentas TRI');

INSERT OR IGNORE INTO dim_activo (activo_key, fondo_key, nombre, tipo) VALUES
  ('INMOSA',      'TRI',    'INMOSA',         'inmobiliario'),
  ('PT',          'PT',        'Parque Titanium','oficina'),
  ('Viña Centro', 'TRI',    'Viña Centro',    'retail'),
  ('Mall Curicó', 'TRI',    'Mall Curicó',    'retail'),
  ('Apoquindo',   'Apo', 'Fondo Apoquindo','oficina'),
  ('Apo3001',     'TRI',    'Apoquindo 3001', 'oficina');

INSERT OR IGNORE INTO dim_serie (nemotecnico, fondo_key, serie) VALUES
  ('CFITRIPT-E', 'PT',     'Única'),
  ('CFITOERI1A', 'TRI', 'A'),
  ('CFITOERI1C', 'TRI', 'C'),
  ('CFITOERI1I', 'TRI', 'I');
