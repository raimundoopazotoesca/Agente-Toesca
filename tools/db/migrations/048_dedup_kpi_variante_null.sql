-- SQLite considera distintos dos NULL dentro de una restricción UNIQUE.
-- El PK lógico de derived_kpi usa variante=NULL para KPIs sin variante, por lo
-- que se acumulaban duplicados. Conservar la fila más reciente y reforzar la
-- unicidad usando la representación normalizada de variante.

DELETE FROM derived_kpi
 WHERE variante IS NULL
   AND id NOT IN (
       SELECT MAX(id)
         FROM derived_kpi
        WHERE variante IS NULL
        GROUP BY entidad_tipo, entidad_key, periodo, kpi
   );

CREATE UNIQUE INDEX IF NOT EXISTS uq_derived_kpi_logical
    ON derived_kpi (
        entidad_tipo,
        entidad_key,
        periodo,
        kpi,
        COALESCE(variante, '')
    );
