-- Migration 031: corrige nemotecnico de la serie Apo en dim_serie.
--
-- Migration 017 introdujo la clave interna 'APO-UNICA' para la serie única
-- de Apo (no transa en bolsa, sin código CMF real). Pero toda la ingesta
-- posterior (raw_dividendo_line, raw_valor_cuota_line, raw_cuota_en_circulacion_line)
-- usa nemotecnico='Apo' para identificar la serie. El mismatch rompe joins
-- contra dim_serie (p.ej. dividend_yield_con_amort). Se alinea dim_serie
-- con la clave realmente usada en los raw_* (la fuente de mayor volumen).

UPDATE dim_serie SET nemotecnico = 'Apo' WHERE nemotecnico = 'APO-UNICA';
