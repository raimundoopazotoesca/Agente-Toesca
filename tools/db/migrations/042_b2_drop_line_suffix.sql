-- B2: Sufijo `_line` reservado para tablas cuyas filas son literalmente líneas
-- de un documento (EEFF, ER activo, flujo, rent roll). Se retira de tablas de
-- observaciones puntuales, snapshots y eventos.
--
-- Vistas de compatibilidad se crean con los nombres viejos para no romper
-- consumidores externos (skill real-estate-finance-expert, código no actualizado).

ALTER TABLE raw_amortizacion_line          RENAME TO raw_amortizacion;
ALTER TABLE raw_ar_event_line              RENAME TO raw_ar_event;
ALTER TABLE raw_caja_line                  RENAME TO raw_caja;
ALTER TABLE raw_capital_suscrito_line      RENAME TO raw_capital_suscrito;
ALTER TABLE raw_cuota_en_circulacion_line  RENAME TO raw_cuota_en_circulacion;
ALTER TABLE raw_dividendo_line             RENAME TO raw_dividendo;
ALTER TABLE raw_saldo_deuda_line           RENAME TO raw_saldo_deuda;
ALTER TABLE raw_valor_cuota_bursatil_line  RENAME TO raw_valor_cuota_bursatil;
ALTER TABLE raw_valor_cuota_contable_line  RENAME TO raw_valor_cuota_contable;

-- Vistas de compatibilidad (permiten leer con el nombre antiguo).
CREATE VIEW raw_amortizacion_line          AS SELECT * FROM raw_amortizacion;
CREATE VIEW raw_ar_event_line              AS SELECT * FROM raw_ar_event;
CREATE VIEW raw_caja_line                  AS SELECT * FROM raw_caja;
CREATE VIEW raw_capital_suscrito_line      AS SELECT * FROM raw_capital_suscrito;
CREATE VIEW raw_cuota_en_circulacion_line  AS SELECT * FROM raw_cuota_en_circulacion;
CREATE VIEW raw_dividendo_line             AS SELECT * FROM raw_dividendo;
CREATE VIEW raw_saldo_deuda_line           AS SELECT * FROM raw_saldo_deuda;
CREATE VIEW raw_valor_cuota_bursatil_line  AS SELECT * FROM raw_valor_cuota_bursatil;
CREATE VIEW raw_valor_cuota_contable_line  AS SELECT * FROM raw_valor_cuota_contable;
