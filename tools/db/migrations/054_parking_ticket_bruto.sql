-- La planilla 'Parking PT DB.xlsx' agregó la columna 'Total Bruto' (hoja
-- Tickets, col H): monto CLP bruto facturado ese día. Sirve para estimar
-- tiempo promedio de estadía / % ocupación cruzando contra la tarifa SABA
-- (no se calcula en esta migración, solo se persiste el dato crudo).
ALTER TABLE raw_parking_ticket_line ADD COLUMN monto_bruto_clp REAL;
