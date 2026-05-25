-- Metadata de activos para NOI: participación del fondo y categoría.
-- Machalí excluido (ya no es parte del portfolio).

ALTER TABLE dim_activo ADD COLUMN participacion REAL;
ALTER TABLE dim_activo ADD COLUMN categoria TEXT;

-- Activo nuevo presente en el NOI- RCSD pero no sembrado antes.
INSERT OR IGNORE INTO dim_activo (activo_key, fondo_key, nombre, tipo) VALUES
  ('Sucden', 'TRI', 'Bodegas Sucden', 'industrial');

-- Participación (de la hoja 'Porcentaje fondos' del CDG) + categoría.
UPDATE dim_activo SET participacion = 0.43, categoria = 'Residencias'        WHERE activo_key = 'INMOSA';
UPDATE dim_activo SET participacion = 1.0,  categoria = 'Industrial'          WHERE activo_key = 'Sucden';
UPDATE dim_activo SET participacion = 0.333,categoria = 'Oficinas'            WHERE activo_key = 'PT';
UPDATE dim_activo SET participacion = 1.0,  categoria = 'Centros Comerciales' WHERE activo_key = 'Viña Centro';
UPDATE dim_activo SET participacion = 0.3,  categoria = 'Oficinas'            WHERE activo_key = 'Apoquindo';
UPDATE dim_activo SET participacion = 1.0,  categoria = 'Oficinas'            WHERE activo_key = 'Apo3001';
UPDATE dim_activo SET participacion = 0.8,  categoria = 'Centros Comerciales' WHERE activo_key = 'Mall Curicó';
