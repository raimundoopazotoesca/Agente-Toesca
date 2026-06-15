-- Agrega transa_bolsa a dim_serie e inserta la serie del fondo Apo.
--
-- Reglas:
--   TRI  → 3 series (A, C, I), todas transan en bolsa. Nemotécnicos CMF: CFITOERI1A/C/I.
--   PT   → 1 serie (Única), transa en bolsa. Nemotécnico CMF: CFITRIPT-E.
--   Apo  → 1 serie (Única), NO transa en bolsa. Sin nemotécnico CMF real.
--          Se usa la clave interna 'APO-UNICA' como PK (no es un código CMF).
--
-- El nemotécnico es el código identificador de la serie en el mercado bursátil (CMF/Bolsa).
-- Si transa_bolsa = 0, el campo nemotecnico es una clave interna, no un código de mercado.

ALTER TABLE dim_serie ADD COLUMN transa_bolsa INTEGER NOT NULL DEFAULT 1;

-- Apo no transa en bolsa
INSERT OR IGNORE INTO dim_serie (nemotecnico, fondo_key, serie, transa_bolsa)
VALUES ('APO-UNICA', 'Apo', 'Única', 0);

-- Las series existentes (TRI A/C/I y PT-E) ya tienen transa_bolsa=1 por DEFAULT.
