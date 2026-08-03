-- 076: absorción histórica derivada desde raw_movimiento_contrato.
--
-- Regla confirmada por el usuario 2026-08-03:
-- - 'Nuevo Contrato' -> +m2, período = inicio_nuevo_contrato.
-- - 'Término' -> -m2, período = vencimiento.
-- - 'Renovó'/'Renovación' -> 0 (mismo arrendatario sigue ocupando; el archivo
--   no trae m2 antes/después desglosado, solo un M2 único).
-- - Excluye tipo_unidad = 'Estacionamientos' (consistente con v_vacancia_activo).
--
-- Ver [[project-absorcion-historica-manual]].

CREATE VIEW v_absorcion_movimiento AS
SELECT
    activo_key,
    tipo_unidad,
    status,
    CASE status
        WHEN 'Nuevo Contrato' THEN substr(inicio_nuevo_contrato, 1, 7)
        WHEN 'Término'        THEN substr(vencimiento, 1, 7)
        ELSE NULL
    END AS periodo,
    CASE status
        WHEN 'Nuevo Contrato' THEN m2
        WHEN 'Término'        THEN -m2
        ELSE 0
    END AS m2_absorcion,
    id AS movimiento_id
FROM raw_movimiento_contrato
WHERE superseded_at IS NULL
  AND (tipo_unidad IS NULL OR tipo_unidad != 'Estacionamientos');

-- Absorción neta por activo y período (colapsa tipo_unidad y movimientos).
CREATE VIEW v_absorcion_activo AS
SELECT activo_key, periodo, SUM(m2_absorcion) AS m2_absorcion_neta
FROM v_absorcion_movimiento
WHERE periodo IS NOT NULL
GROUP BY activo_key, periodo;
