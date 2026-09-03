"""Canonical SQL surface registry for schema84 (BASELINE_VERSION).

Deny-by-default: any schema object not explicitly listed here classifies as
UNCLASSIFIED and is never queryable. New objects (new tables, new views,
migrations 085+) must be added to a bucket explicitly before becoming visible
to SchemaSearch or RunSql.
"""
from __future__ import annotations

from typing import Literal

MODEL_QUERYABLE_TABLES: frozenset[str] = frozenset({
    "derived_kpi",
    "dim_activo",
    "dim_concepto_parking",
    "dim_credito",
    "dim_cuenta_eeff",
    "dim_fondo",
    "dim_residencia",
    "dim_serie",
    "dim_sociedad",
    "fact_adquisicion",
    "fact_tasacion",
    "ingest_run",
    "raw_amortizacion",
    "raw_amortizacion_extraordinaria",
    "raw_ar_event",
    "raw_balance_consolidado_line",
    "raw_caja",
    "raw_capital_suscrito",
    "raw_cuota_en_circulacion",
    "raw_dividendo",
    "raw_dolar_diaria",
    "raw_eeff_line",
    "raw_er_activo_line",
    "raw_flujo_line",
    "raw_mercado_bodegas",
    "raw_mercado_bodegas_evolucion",
    "raw_mercado_comercio",
    "raw_mercado_oficinas",
    "raw_mercado_oficinas_evolucion",
    "raw_movimiento_contrato",
    "raw_ocupacion_residencia_line",
    "raw_pagare_intercompania",
    "raw_parking_facturacion_line",
    "raw_parking_gasto_line",
    "raw_parking_ingreso_line",
    "raw_parking_ticket_line",
    "raw_rent_roll_line",
    "raw_saldo_deuda",
    "raw_uf_diaria",
    "raw_vacancia_manual",
    "raw_valor_cuota_bursatil",
    "raw_valor_cuota_contable",
    "raw_variacion_comercio_rm",
    "sucden_valores_fijos",
})

MODEL_QUERYABLE_VIEWS: frozenset[str] = frozenset({
    "fact_dividendo",
    "fact_dolar",
    "fact_precio_cuota",
    "fact_uf",
    "raw_amortizacion_line",
    "raw_ar_event_line",
    "raw_caja_line",
    "raw_capital_suscrito_line",
    "raw_cuota_en_circulacion_line",
    "raw_dividendo_line",
    "raw_saldo_deuda_line",
    "raw_valor_cuota_bursatil_line",
    "raw_valor_cuota_contable_line",
    "raw_valor_cuota_line",
    "v_absorcion_activo",
    "v_absorcion_movimiento",
    "v_activo_fondo_efectivo",
    "v_capital_suscrito_serie",
    "v_flujos_tir_serie",
    "v_ocupacion_inmosa_consolidado",
    "v_ocupacion_inmosa_vigente",
    "v_parking_mensual",
    "v_parking_ocupacion_diaria",
    "v_parking_ocupacion_mensual",
    "v_parking_ratio_no_abonados",
    "v_parking_resultado_uf",
    "v_rent_roll_semantic",
    "v_serie_patrimonio",
    "v_vacancia_activo",
    "v_vacancia_activo_efectivo",
    "v_vacancia_activo_tipo",
    "v_vacancia_apoquindo_consolidado_tipo",
    "v_vacancia_pt_consolidado_tipo",
})

MODEL_QUERYABLE: frozenset[str] = MODEL_QUERYABLE_TABLES | MODEL_QUERYABLE_VIEWS

INTERNAL: frozenset[str] = frozenset({"dim_kpi", "schema_version"})

SQLITE_INTERNAL: frozenset[str] = frozenset({"sqlite_sequence"})

Bucket = Literal["MODEL_QUERYABLE", "INTERNAL", "SQLITE_INTERNAL", "UNCLASSIFIED"]


def classify(name: str) -> Bucket:
    """Classify a schema object name into its surface bucket. Deny-by-default."""
    if name in MODEL_QUERYABLE:
        return "MODEL_QUERYABLE"
    if name in INTERNAL:
        return "INTERNAL"
    if name in SQLITE_INTERNAL:
        return "SQLITE_INTERNAL"
    return "UNCLASSIFIED"


def is_queryable(name: str) -> bool:
    """True only for objects in the MODEL_QUERYABLE bucket."""
    return name in MODEL_QUERYABLE
