-- Drop tablas redundantes verificadas contra fuentes alternativas.
--
-- raw_patrimonio_bursatil_line:
--   patrimonio_bursatil_uf = precio_uf * n_cuotas → derivable/persistido en
--   raw_valor_cuota_bursatil_line.patrimonio_bursatil_uf. Datos migrados.
--
-- raw_capital_movimiento_line:
--   Aportes/disminuciones a nivel fondo (EEFF Estado Cambios Patrimonio).
--   Redundante con raw_ar_event_line (mismo evento, mayor granularidad por serie
--   desde CDG A&R Rentas). Cross-check verificado: delta 0 UF vs capital suscrito
--   final por serie (TRI). Tabla estaba vacía (0 filas).

DROP INDEX IF EXISTS idx_cap_mov_periodo;
DROP TABLE IF EXISTS raw_capital_movimiento_line;
DROP TABLE IF EXISTS raw_patrimonio_bursatil_line;
