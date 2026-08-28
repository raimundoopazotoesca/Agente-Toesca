-- 089: backfill determinístico de procedencia en el histórico de rent roll.
--
-- Confirmado con el usuario 2026-08-28.
--
-- La migración 085 agregó `fuente_proveedor` / `fuente_formato` como nullable
-- justamente para NO asignar 'JLL' por default: el histórico mezcla proveedores
-- y eso habría inventado procedencia.
--
-- La derivación se hace desde `source_file`, no desde `ingest_run.tool`. El tool
-- resultó NO ser evidencia válida: `ingest_rent_roll_validated:jll` produjo
-- también las filas de Viña Centro y Mall Curicó, que son de Tres Asociados. El
-- nombre de archivo, en cambio, particiona el histórico sin solapamiento:
--
--   Rent Roll y NOI Junio.xlsx        2067 filas  Apo3001/4501/4700, Boulevard, Torre A
--   Excel Tres A Viña Mayo 2026.xlsx    90 filas  Viña Centro
--   Excel Tres A Curicó Mayo 2026.xlsx  49 filas  Mall Curicó
--   Contratos Sucden e INMOSA.xlsx      24 filas  Sucden + Residencias
--
-- Sólo se escribe donde el patrón es inequívoco. Lo que no calce queda en NULL
-- (procedencia no declarada) y se contabiliza como 'legacy_unknown' más abajo:
-- preferimos un hueco explícito antes que una atribución adivinada.
--
-- `fuente_formato` distingue la era: 'jll_v1' es el "{AAMM} Rent Roll y NOI",
-- reemplazado por 'jll_v2' (la planilla única). Ninguna fila histórica es v2.

UPDATE raw_rent_roll_line
   SET fuente_proveedor = 'JLL',
       fuente_formato   = 'jll_v1'
 WHERE fuente_proveedor IS NULL
   AND source_file LIKE '%Rent Roll y NOI%';

UPDATE raw_rent_roll_line
   SET fuente_proveedor = 'TresA',
       fuente_formato   = 'tresa_v1'
 WHERE fuente_proveedor IS NULL
   AND source_file LIKE 'Excel Tres A%';

-- Carga interna a partir de contratos, no de un proveedor externo.
UPDATE raw_rent_roll_line
   SET fuente_proveedor = 'interno',
       fuente_formato   = 'contratos_v1'
 WHERE fuente_proveedor IS NULL
   AND source_file LIKE '%Contratos Sucden e INMOSA%';

-- Resto: procedencia no derivable. Se marca explícitamente en vez de dejarlo
-- indistinguible de una fila nueva a la que se le olvidó declararla.
UPDATE raw_rent_roll_line
   SET fuente_proveedor = 'legacy_unknown'
 WHERE fuente_proveedor IS NULL;
