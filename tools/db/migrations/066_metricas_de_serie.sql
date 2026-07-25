-- 066: separar las métricas de serie de las cuentas contables.
--
-- Las filas cuyo `cuenta_nombre` empieza con "Serie <X> - " (1.264 filas vivas:
-- Valor Cuota Libro, Valor Cuota Mercado, Patrimonio, Aportantes N°) NO son
-- cuentas de ESF, ER, EFE ni ECP: son métricas por serie que ya tienen tablas
-- propias (`raw_valor_cuota_contable`, `raw_valor_cuota_bursatil`,
-- `raw_cuota_en_circulacion`, vista `v_serie_patrimonio`).
--
-- Estaban entre los nombres más frecuentes sin mapear e inflaban artificialmente
-- el trabajo pendiente de mapeo canónico. Marcarlas evita además que entren en
-- deduplicaciones de cuentas o que alguien las sume como si fueran partidas
-- contables — que sería doble conteo respecto de sus tablas especializadas.
--
-- Se preservan para trazabilidad (vienen del documento), pero quedan fuera del
-- perímetro contable: `seccion = 'METRICA_SERIE'` y sin `cuenta_codigo_canonical`.
-- Las ingestas nuevas deben dirigir estas métricas a sus tablas especializadas.

UPDATE raw_eeff_line
   SET seccion = 'METRICA_SERIE',
       seccion_original = COALESCE(seccion_original, cuenta_nombre)
 WHERE cuenta_nombre LIKE 'Serie %'
   AND cuenta_nombre LIKE '%-%'
   AND cuenta_codigo_canonical IS NULL
   AND seccion IS NULL;
