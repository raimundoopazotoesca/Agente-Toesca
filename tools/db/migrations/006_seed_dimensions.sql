-- Seeds de dimensiones desde catálogos hardcoded en código.
-- INSERT OR IGNORE para que la migración sea segura ante reaplicaciones manuales.

INSERT OR IGNORE INTO dim_fondo (fondo_key, nombre, sharepoint_folder) VALUES
  ('A&R Apoquindo', 'Toesca Rentas Inmobiliarias Apoquindo', 'Fondos\Rentas Apoquindo'),
  ('A&R PT',        'Toesca Rentas Inmobiliarias PT',        'Fondos\Rentas PT'),
  ('A&R Rentas',    'Toesca Rentas Inmobiliarias',           'Fondos\Rentas TRI');

INSERT OR IGNORE INTO dim_activo (activo_key, fondo_key, nombre, tipo) VALUES
  ('INMOSA',      'A&R Rentas',    'INMOSA',         'inmobiliario'),
  ('PT',          'A&R PT',        'Parque Titanium','oficina'),
  ('Viña Centro', 'A&R Rentas',    'Viña Centro',    'retail'),
  ('Mall Curicó', 'A&R Rentas',    'Mall Curicó',    'retail'),
  ('Apoquindo',   'A&R Apoquindo', 'Fondo Apoquindo','oficina'),
  ('Apo3001',     'A&R Apoquindo', 'Apoquindo 3001', 'oficina');

INSERT OR IGNORE INTO dim_serie (nemotecnico, fondo_key, serie) VALUES
  ('CFITRIPT-E', 'A&R PT',     'Única'),
  ('CFITOERI1A', 'A&R Rentas', 'A'),
  ('CFITOERI1C', 'A&R Rentas', 'C'),
  ('CFITOERI1I', 'A&R Rentas', 'I');
