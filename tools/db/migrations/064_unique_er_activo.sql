-- 064: unicidad de raw_er_activo_line, con la clave correcta.
--
-- La clave que declaraban las migraciones históricas, (file_hash, source_row),
-- es incorrecta aquí: las planillas de ER traen los meses en columnas, así que
-- una fila de origen genera legítimamente una fila POR PERÍODO (verificado un
-- caso con 104 filas compartiendo file_hash+source_row).
--
-- Pero (file_hash, source_row, periodo) tampoco basta: dejaba 10 "sobrantes"
-- que resultaron NO ser duplicados, sino un reparto deliberado —una sola fila
-- del archivo con las contribuciones combinadas de Apoquindo, dividida 75/25
-- entre Apo4501 y Apo4700, con la regla escrita en el propio cuenta_nombre
-- ("Contribuciones (split 75% s/combinado, regla 2026-07-09)"). Ratio 3,0 exacto.
--
-- La clave incluye por tanto `activo_key`: una fila de origen PUEDE repartirse
-- entre activos, pero NO puede repetirse para el mismo activo y período.
-- Verificado: 0 filas sobrantes con esta clave, así que no requiere saneamiento.
-- Ver docs/analisis-saneamiento-fase2.md §1.

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_er_activo_hash_row_periodo_activo
    ON raw_er_activo_line(file_hash, source_row, periodo, activo_key);
