-- 091: exponer la semantica de renta en el dataset gobernado de rent roll.
--
-- v_rent_roll_semantic publicaba `renta_uf` como un campo unico, y el catalogo
-- lo declaraba como tasa UF/m2 (medida `rent_rate_uf_m2`). Eso era cierto para
-- el formato clasico pero deja de serlo con JLL v2, donde `renta_uf` es el
-- total UF y la tasa vive en `renta_uf_m2` (migracion 085).
--
-- Publicar un solo campo con dos significados posibles es exactamente el modo
-- de falla que el invariante de semantica no mixta evita a nivel de fila. Aca se
-- resuelve a nivel de contrato: se exponen los tres campos por separado y el
-- consumidor elige cual necesita, sin tener que saber de que era es la fila.
--
--   renta_semantica       'total_uf' | 'tasa_uf_m2' | 'indeterminada'
--   renta_total_uf        monto UF/mes, o NULL si la fila no lo tiene
--   renta_uf_m2           tasa UF/m2/mes, o NULL si la fila no la tiene
--
-- `renta_uf` se conserva sin cambios para no romper consumidores existentes,
-- pero queda desaconsejado: su unidad depende de `renta_semantica`.

DROP VIEW IF EXISTS v_rent_roll_semantic;

CREATE VIEW v_rent_roll_semantic AS
SELECT
    'rent_roll' AS dataset_key,
    'rent_roll_semantics_v1' AS semantic_version,
    r.activo_key,
    r.periodo,
    r.unidad,
    CASE
        WHEN r.unidad LIKE '(sin detalle, fila %)' THEN 'synthetic_missing_source_identity'
        ELSE 'source_identity'
    END AS unit_identity_quality,
    r.arrendatario,
    r.m2,
    r.renta_uf,
    COALESCE(r.renta_semantica, 'indeterminada') AS renta_semantica,
    -- Sólo se expone el total cuando la fila declara tenerlo. Derivarlo de la
    -- tasa para el histórico seria inventar un dato que aun no esta demostrado
    -- por activo (ver docs/rent-roll-renta-semantics-v1.md).
    CASE WHEN r.renta_semantica = 'total_uf' THEN r.renta_uf END AS renta_total_uf,
    COALESCE(
        r.renta_uf_m2,
        CASE WHEN COALESCE(r.renta_semantica, 'indeterminada') <> 'total_uf'
             THEN r.renta_uf END
    ) AS renta_uf_m2,
    r.fuente_proveedor,
    r.fuente_formato,
    r.fecha_corte_fuente,
    CASE
        WHEN LOWER(TRIM(r.arrendatario)) = 'vacante' THEN 'vacant'
        WHEN r.arrendatario IS NULL OR TRIM(r.arrendatario) = '' THEN 'unknown'
        WHEN LOWER(TRIM(r.arrendatario)) LIKE '%vacante%' THEN 'unknown'
        ELSE 'occupied'
    END AS occupancy_status,
    CASE
        WHEN json_extract(r.extra_json, '$.tipo_activo_2') IS NULL
          OR TRIM(json_extract(r.extra_json, '$.tipo_activo_2')) = '' THEN 'unknown'
        WHEN LOWER(TRIM(json_extract(r.extra_json, '$.tipo_activo_2'))) = 'oficina' THEN 'office'
        WHEN LOWER(TRIM(json_extract(r.extra_json, '$.tipo_activo_2'))) = 'local' THEN 'local'
        WHEN LOWER(TRIM(json_extract(r.extra_json, '$.tipo_activo_2'))) = 'bodega' THEN 'storage'
        WHEN LOWER(TRIM(json_extract(r.extra_json, '$.tipo_activo_2'))) IN ('estacionamiento', 'parking') THEN 'parking'
        WHEN LOWER(TRIM(json_extract(r.extra_json, '$.tipo_activo_2'))) = 'ug' THEN 'storage_unit_pending'
        ELSE 'other_source_declared'
    END AS unit_category,
    json_extract(r.extra_json, '$.tipo_activo_2') AS unit_category_source,
    CASE WHEN r.superseded_at IS NULL THEN 1 ELSE 0 END AS is_current,
    r.source_file,
    r.source_sheet,
    r.source_row,
    r.file_hash,
    r.ingest_run_id
FROM raw_rent_roll_line r;
