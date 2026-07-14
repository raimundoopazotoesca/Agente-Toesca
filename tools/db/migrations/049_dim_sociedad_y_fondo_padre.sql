-- Agrega jerarquía sociedad + fondo padre para consolidación TRI.
-- Aditivo puro: no toca columnas ni valores existentes.

-- ── 1. Sociedades / holdings intermedias ─────────────────────────────────────
CREATE TABLE dim_sociedad (
  sociedad_key TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  fondo_key TEXT NOT NULL REFERENCES dim_fondo(fondo_key),
  participacion_fondo_en_sociedad REAL NOT NULL
);

INSERT INTO dim_sociedad (sociedad_key, nombre, fondo_key, participacion_fondo_en_sociedad) VALUES
  ('Chanarcillo',   'Inmobiliaria Chañarcillo Ltda',                             'TRI', 1.0),
  ('CuricoSpA',     'Power Center Curicó SpA',                                   'TRI', 0.80),
  ('SeniorAssist',  'Inmobiliaria e Inversiones Senior Assist Chile S.A.',       'TRI', 0.43),
  ('VCSpA',         'Inmobiliaria VC SpA / Viña Centro SpA (colapsada)',         'TRI', 1.0),
  ('TorreASA',      'Torre A S.A.',                                              'PT',  1.0),
  ('BlvdSpA',       'Inmobiliaria Boulevard PT SpA',                             'PT',  1.0),
  ('ApoquindoSpA',  'Inmobiliaria Apoquindo SpA',                                'Apo', 1.0);

-- ── 2. Activo ↔ sociedad ─────────────────────────────────────────────────────
ALTER TABLE dim_activo ADD COLUMN sociedad_key TEXT REFERENCES dim_sociedad(sociedad_key);
ALTER TABLE dim_activo ADD COLUMN participacion_en_sociedad REAL;

UPDATE dim_activo SET sociedad_key='Chanarcillo',   participacion_en_sociedad=1.0    WHERE activo_key='Sucden';
UPDATE dim_activo SET sociedad_key='Chanarcillo',   participacion_en_sociedad=0.685  WHERE activo_key='Apo3001';
UPDATE dim_activo SET sociedad_key='VCSpA',         participacion_en_sociedad=1.0    WHERE activo_key='Viña Centro';
UPDATE dim_activo SET sociedad_key='CuricoSpA',     participacion_en_sociedad=1.0    WHERE activo_key='Mall Curicó';
UPDATE dim_activo SET sociedad_key='SeniorAssist',  participacion_en_sociedad=1.0    WHERE activo_key='INMOSA';
UPDATE dim_activo SET sociedad_key='TorreASA',      participacion_en_sociedad=1.0    WHERE activo_key='Torre A';
UPDATE dim_activo SET sociedad_key='BlvdSpA',       participacion_en_sociedad=1.0    WHERE activo_key='Boulevard';
UPDATE dim_activo SET sociedad_key='ApoquindoSpA',  participacion_en_sociedad=1.0    WHERE activo_key='Apo4501';
UPDATE dim_activo SET sociedad_key='ApoquindoSpA',  participacion_en_sociedad=1.0    WHERE activo_key='Apo4700';

-- ── 3. Subfondos ─────────────────────────────────────────────────────────────
ALTER TABLE dim_fondo ADD COLUMN fondo_padre TEXT REFERENCES dim_fondo(fondo_key);
ALTER TABLE dim_fondo ADD COLUMN participacion_en_padre REAL;

UPDATE dim_fondo SET fondo_padre='TRI', participacion_en_padre=0.333 WHERE fondo_key='PT';
UPDATE dim_fondo SET fondo_padre='TRI', participacion_en_padre=0.30  WHERE fondo_key='Apo';

-- ── 4. Vista look-through ────────────────────────────────────────────────────
CREATE VIEW v_activo_fondo_efectivo AS
  SELECT
    a.activo_key,
    s.fondo_key AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad AS participacion_efectiva,
    'directa' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  WHERE a.sociedad_key IS NOT NULL
  UNION ALL
  SELECT
    a.activo_key,
    f.fondo_padre AS fondo_key,
    a.participacion_en_sociedad * s.participacion_fondo_en_sociedad * f.participacion_en_padre AS participacion_efectiva,
    'lookthrough' AS via
  FROM dim_activo a
  JOIN dim_sociedad s ON a.sociedad_key = s.sociedad_key
  JOIN dim_fondo   f ON s.fondo_key    = f.fondo_key
  WHERE a.sociedad_key IS NOT NULL
    AND f.fondo_padre IS NOT NULL;
