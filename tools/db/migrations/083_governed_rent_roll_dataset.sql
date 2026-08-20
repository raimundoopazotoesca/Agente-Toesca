-- Governed row-level rent roll semantics. This migration preserves raw rows,
-- including superseded history, and derives classification fields once.
-- Legacy db_chat guidance and ingestion helper predicates are not authorities
-- for consumers of this governed dataset; align or retire them separately.
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
