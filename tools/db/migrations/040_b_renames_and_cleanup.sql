-- Renombres semánticos y limpieza (B1 + B3 aprobados 2026-07-01)
--
-- B1: unificar nombres de misma cosa
ALTER TABLE raw_valor_cuota_bursatil_line RENAME COLUMN n_cuotas TO cuotas;
ALTER TABLE dim_activo RENAME COLUMN participacion TO participacion_fondo_activo;
ALTER TABLE dim_credito RENAME COLUMN part_fondo TO participacion_fondo_deuda;
ALTER TABLE raw_pagare_intercompania RENAME COLUMN tasa TO tasa_anual;

-- B3: nombres poco claros
ALTER TABLE raw_deuda_saldo_line RENAME TO raw_saldo_deuda_line;
ALTER TABLE derived_kpi RENAME COLUMN recipe TO formula;
ALTER TABLE dim_cuenta_eeff RENAME COLUMN source_sheet TO seccion_eeff;

-- raw_ar_event_line: purgar filas redundantes con tablas dedicadas.
-- La tabla ahora contiene solo eventos A&R puros: Aporte, Disminucion, Canje Cuotas.
-- (Dividendo → raw_dividendo_line; VR Bursatil → raw_valor_cuota_bursatil_line;
--  VR Contable → raw_valor_cuota_contable_line)
DELETE FROM raw_ar_event_line WHERE detalle IN ('Dividendo', 'VR Bursatil', 'VR Contable');
