-- 069: Etapa 1 del mapeo canónico — el único hueco funcional que es mapeable.
--
-- De los 15 huecos que reportaba la cobertura funcional, **14 son ausencias
-- legítimas**: se verificó uno por uno que no existe ningún nombre sin mapear que
-- corresponda a esa cuenta en ese período. El documento simplemente no la trae.
--
--   Apo, ER.costos_transaccion (7 cierres de 2019-2020 y 2025)
--       "Costos de transacción" es un nombre inequívoco y sí está mapeado donde
--       aparece (83 filas). En estos cierres no figura en el EEFF.
--   Apo, ER.otros_gastos (2025-09 y 2025-12)
--       Lo único parecido es "Otros gastos de operación **pagados**", que es una
--       línea del ESTADO DE FLUJOS, no del de resultados: nunca se mapea a ER
--       (141 filas, ninguna mapeada). Mapearla sería mezclar dos estados.
--   PT 2017-06, las otras 5 cuentas de gasto
--       El fondo inició operaciones el 16-nov-2017: a junio de ese año no tenía
--       gastos de operación desglosados. Todas sus líneas de resultado están en 0
--       salvo dividendos e intereses.
--
-- El único mapeable, con respaldo de fuente y sección:
--
--   PT 2017-06 · "Otros gastos de operación" · −1.609.000
--     · el nombre exacto está mapeado a ER.otros_gastos en otros 90 registros
--     · es sección ER (no dice "pagados", que sería EFE)
--     · PT 2017-06 no tiene ya ER.otros_gastos → no genera duplicado
--
-- NO se mapean en bloque las otras 25 filas de PT con ese mismo nombre: en la
-- mayoría de esos períodos ya existe una contraparte mapeada por carga manual
-- (p. ej. PT 2025-12 tiene −343.000 dos veces, una sin mapear y otra ya mapeada
-- desde "EEFF PT 2025-12 (manual)"). Mapearlas duplicaría el gasto.

UPDATE raw_eeff_line
   SET cuenta_codigo_canonical = 'ER.otros_gastos',
       seccion = 'ER'
 WHERE fondo_key = 'PT'
   AND periodo   = '2017-06'
   AND lower(cuenta_nombre) = 'otros gastos de operación'
   AND cuenta_codigo_canonical IS NULL
   AND superseded_at IS NULL;
