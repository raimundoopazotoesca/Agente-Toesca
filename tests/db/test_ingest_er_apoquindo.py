"""Tests para tools.db.ingest_er_apoquindo."""
from __future__ import annotations

import os
import tempfile
from datetime import date

import openpyxl
import pytest

from tools.db import ingest_er_apoquindo as mod


# ── Fixture xlsx con 3 meses × 2 activos × 10 categorías ────────────────────

_MESES_HEADER = ["dic-24", "ene-25", "feb-25"]
_PERIODOS = ["2024-12", "2025-01", "2025-02"]

_CATS_ORDER = [
    ("(-) Ingresos por Arriendos",       "APO_ING_ARR",   +1),
    ("(-) Gastos Comunes/Vacancia",      "APO_GC_VAC",    -1),
    ("(-) Comisión Corredor",            "APO_COM_CORR",  -1),
    ("(-) Administración",               "APO_ADM",       -1),
    ("Provisión Reparaciones",           "APO_PROV_REP",  -1),
    ("(-) Gastos Bono + Legales + Otros","APO_BONOS_LEG", -1),
    ("(-) Gastos Constructores Asociados (Contabilidad)", "APO_CONSTRUCT", -1),
    ("(-) Gastos IVA no recuperado/Otros Gastos", "APO_IVA_NR", -1),
    ("(-) Contribuciones",               "APO_CONTRIB",   -1),
    ("(-) Seguros",                      "APO_SEG",       -1),
]


def _build_fixture_xlsx(tmp_path) -> str:
    """Construye un xlsx con el layout esperado y valores previsibles.

    monto_activo = mes_index * 1000 + cat_index * 100  (signo aplicado).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Apo"
    # Fila 1: A vacío, luego meses
    ws.cell(row=1, column=1).value = "Fondo Apoquindo"
    for j, m in enumerate(_MESES_HEADER, start=2):
        ws.cell(row=1, column=j).value = m
    r = 2
    for cat_idx, (label, _, sign) in enumerate(_CATS_ORDER):
        ws.cell(row=r, column=1).value = label
        r += 1
        # Sub-fila 4700
        ws.cell(row=r, column=1).value = "Apoquindo 4700"
        for mi, _ in enumerate(_MESES_HEADER):
            ws.cell(row=r, column=2 + mi).value = sign * (mi * 1000 + cat_idx * 100 + 47)
        r += 1
        # Sub-fila 4501
        ws.cell(row=r, column=1).value = "Apoquindo 4501"
        for mi, _ in enumerate(_MESES_HEADER):
            ws.cell(row=r, column=2 + mi).value = sign * (mi * 1000 + cat_idx * 100 + 45)
        r += 1
    # Fila NOI Mensual (debe ignorarse)
    ws.cell(row=r, column=1).value = "NOI Mensual"
    for mi in range(len(_MESES_HEADER)):
        ws.cell(row=r, column=2 + mi).value = 99999
    path = os.path.join(tmp_path, "apo_fixture.xlsx")
    wb.save(path)
    return path


@pytest.fixture
def fixture_xlsx(tmp_path):
    return _build_fixture_xlsx(str(tmp_path))


# ── Tests ────────────────────────────────────────────────────────────────────

def test_parse_devuelve_60_filas(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # 3 meses × 2 activos × 10 categorías
    assert len(rows) == 60


def test_parse_activo_keys(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    activos = {r["activo_key"] for r in rows}
    assert activos == {"Apo4501", "Apo4700"}


def test_parse_periodos_yyyy_mm(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    periodos = {r["periodo"] for r in rows}
    assert periodos == {"2024-12", "2025-01", "2025-02"}


def test_parse_pseudo_codigos_completos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    codigos = {r["cuenta_codigo"] for r in rows}
    esperados = {
        "APO_ING_ARR", "APO_GC_VAC", "APO_COM_CORR", "APO_ADM", "APO_PROV_REP",
        "APO_BONOS_LEG", "APO_CONSTRUCT", "APO_IVA_NR", "APO_CONTRIB", "APO_SEG",
    }
    assert codigos == esperados


def test_parse_signos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # Ingresos por arriendos siempre >0
    ings = [r for r in rows if r["cuenta_codigo"] == "APO_ING_ARR"]
    assert all(r["monto_clp"] > 0 for r in ings)
    # Contribuciones (gasto) siempre <0
    contrib = [r for r in rows if r["cuenta_codigo"] == "APO_CONTRIB"]
    assert all(r["monto_clp"] < 0 for r in contrib)


def test_parse_todas_operacionales(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["es_operacional"] == 1 for r in rows)


def test_parse_noi_row_ignorada(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # 99999 es el valor de la fila NOI del fixture; no debe aparecer
    assert not any(r["monto_clp"] == 99999 for r in rows)


def test_parse_source_metadata(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["source_file"] == fixture_xlsx for r in rows)
    assert all(r["source_sheet"] == "Apo" for r in rows)
    assert all(isinstance(r["source_row"], int) and r["source_row"] > 0 for r in rows)


def test_file_hash_estable(fixture_xlsx):
    h1 = mod._file_hash(fixture_xlsx)
    h2 = mod._file_hash(fixture_xlsx)
    assert h1 == h2
    assert len(h1) == 64
