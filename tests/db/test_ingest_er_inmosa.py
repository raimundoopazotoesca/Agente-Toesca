"""Tests para tools.db.ingest_er_inmosa."""
from __future__ import annotations

import os
import sqlite3

import openpyxl
import pytest

from tools.db import ingest_er_inmosa as mod


# ── Fixture xlsx replicando la estructura real de RAW/NOI INMOSA.xlsx ──────
# Fila 3: header de fechas. Fila 4: vacía. Fila 5: ancla "INMOSA".
# Filas 6-14: 9 filas de categoría (fila 7 duplica fila 6). Fila 15: NOI Mensual.
# Valores reales de ene/feb/mar-2018 tomados del archivo fuente.

_PERIODOS = ["2018-01", "2018-02", "2018-03"]
_FECHAS = [
    __import__("datetime").datetime(2018, 1, 31),
    __import__("datetime").datetime(2018, 2, 28),
    __import__("datetime").datetime(2018, 3, 31),
]
_INGRESOS = [6440.0915337339, 6434.459445817043, 6437.583242252402]
_ADMIN = [-175, -175, -175]
_PROV_REP = [-35.82156799923614, -19.76057110904785, -69.61203164324844]
_NOI_ESPERADO = [6229.2699657346675, 6239.698874707995, 6192.971210609153]


def _build_fixture_xlsx(tmp_path, corrupt_noi: bool = False,
                         unknown_label: bool = False) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"

    # Fila 3: header de fechas (col B=2 en adelante)
    for j, f in enumerate(_FECHAS, start=2):
        ws.cell(row=3, column=j).value = f
    # Fila 4: vacía (implícito)
    # Fila 5: ancla
    ws.cell(row=5, column=1).value = "INMOSA"
    # Fila 6-7: Ingresos (duplicado)
    label_ingresos = "(+) Ingresos por Arriendos"
    ws.cell(row=6, column=1).value = label_ingresos
    ws.cell(row=7, column=1).value = label_ingresos
    for j, v in enumerate(_INGRESOS, start=2):
        ws.cell(row=6, column=j).value = v
        ws.cell(row=7, column=j).value = v
    # Fila 8: Contribuciones (vacía en este fixture, como en el ejemplo real)
    ws.cell(row=8, column=1).value = "(+) Contribuciones"
    # Fila 9: Administración (mojibake real)
    ws.cell(row=9, column=1).value = "unknown label xyz" if unknown_label else "(-) Administraci�n"
    for j, v in enumerate(_ADMIN, start=2):
        ws.cell(row=9, column=j).value = v
    # Fila 10: Provision Reparaciones (con espacio final real)
    ws.cell(row=10, column=1).value = "(-) Provision Reparaciones "
    for j, v in enumerate(_PROV_REP, start=2):
        ws.cell(row=10, column=j).value = v
    # Fila 11: Aseo, Mantención y Otros (mojibake, valores 0)
    ws.cell(row=11, column=1).value = "(-) Aseo, Mantenci�n y Otros"
    for j in range(2, 2 + len(_PERIODOS)):
        ws.cell(row=11, column=j).value = 0
    # Fila 12: Otros Gastos Operacionales (vacía)
    ws.cell(row=12, column=1).value = "(-) Otros Gastos Operacionales"
    # Fila 13: IVA (vacía)
    ws.cell(row=13, column=1).value = "(-) IVA"
    # Fila 14: Seguros (valores 0)
    ws.cell(row=14, column=1).value = "(-) Seguros"
    for j in range(2, 2 + len(_PERIODOS)):
        ws.cell(row=14, column=j).value = 0
    # Fila 15: NOI Mensual (control)
    ws.cell(row=15, column=1).value = "NOI Mensual"
    noi_vals = list(_NOI_ESPERADO)
    if corrupt_noi:
        noi_vals[0] += 1000  # rompe la validación de integridad a propósito
    for j, v in enumerate(noi_vals, start=2):
        ws.cell(row=15, column=j).value = v

    os.makedirs(tmp_path, exist_ok=True)
    path = os.path.join(tmp_path, "inmosa_fixture.xlsx")
    wb.save(path)
    return path


@pytest.fixture
def fixture_xlsx(tmp_path):
    return _build_fixture_xlsx(str(tmp_path))


# ── Tests de parsing ─────────────────────────────────────────────────────

def test_parse_devuelve_21_filas(fixture_xlsx):
    # 8 categorías (sin la duplicada) × 3 meses = 24
    # (fixture has 9 category rows: Ingresos duplicated in rows 6-7, then
    # Contribuciones, Administración, Provision Reparaciones, Aseo, Otros Gastos,
    # IVA, Seguros = 8 unique categories)
    rows = mod.parse_planilla(fixture_xlsx)
    assert len(rows) == 24


def test_parse_activo_key_fijo_inmosa(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["activo_key"] == "INMOSA" for r in rows)


def test_parse_periodos_yyyy_mm(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert {r["periodo"] for r in rows} == set(_PERIODOS)


def test_parse_pseudo_codigos_completos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    codigos = {r["cuenta_codigo"] for r in rows}
    esperados = {
        "INMOSA_ING_ARR", "INMOSA_CONTRIB", "INMOSA_ADM", "INMOSA_PROV_REP",
        "INMOSA_ASEO", "INMOSA_OTROS_GASTOS", "INMOSA_IVA", "INMOSA_SEG",
    }
    assert codigos == esperados


def test_parse_ingresos_no_duplicados(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    ing = [r for r in rows if r["cuenta_codigo"] == "INMOSA_ING_ARR"]
    assert len(ing) == 3  # una fila por periodo, no dos


def test_parse_todas_operacionales(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["es_operacional"] == 1 for r in rows)


def test_parse_noi_row_ignorada(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    # La fila "NOI Mensual" nunca debe generar una fila con cuenta_codigo
    # (no hay categoría mapeada para ese label — si apareciera, cat_meta
    # sería None y el parser fallaría en vez de emitir una fila silenciosa).
    assert all(r["cuenta_codigo"] is not None for r in rows)
    # Ningún monto individual persistido iguala el NOI total del periodo
    # (confirma que la fila de control no se coló como si fuera una categoría).
    montos = {round(r["monto_clp"], 4) for r in rows}
    assert not montos & {round(v, 4) for v in _NOI_ESPERADO}


def test_parse_valores_reales_ingresos(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    ing_by_periodo = {r["periodo"]: r["monto_clp"] for r in rows if r["cuenta_codigo"] == "INMOSA_ING_ARR"}
    for periodo, esperado in zip(_PERIODOS, _INGRESOS):
        assert abs(ing_by_periodo[periodo] - esperado) < 1e-6


def test_parse_contribuciones_puede_ser_negativa(tmp_path):
    """Contribuciones con valor negativo se clasifica igual como INGRESOS_OPERACION
    (la seccion no depende del signo del valor, solo del prefijo de la fuente)."""
    path = _build_fixture_xlsx(str(tmp_path))
    wb = openpyxl.load_workbook(path)
    ws = wb["Hoja1"]
    ws.cell(row=8, column=2).value = -1381.0  # Contribuciones ene-2018 negativa
    # Ajustar NOI de ese periodo para que la suma siga cuadrando
    ws.cell(row=15, column=2).value = _NOI_ESPERADO[0] + (-1381.0)
    wb.save(path)

    rows = mod.parse_planilla(path)
    contrib = [r for r in rows if r["cuenta_codigo"] == "INMOSA_CONTRIB" and r["periodo"] == "2018-01"]
    assert len(contrib) == 1
    assert contrib[0]["monto_clp"] == -1381.0
    assert contrib[0]["seccion"] == "INGRESOS_OPERACION"


def test_parse_categoria_desconocida_falla(tmp_path):
    path = _build_fixture_xlsx(str(tmp_path), unknown_label=True)
    with pytest.raises(ValueError, match=r"(?i)categor[ií]a"):
        mod.parse_planilla(path)


def test_parse_validacion_integridad_falla_si_no_cuadra(tmp_path):
    path = _build_fixture_xlsx(str(tmp_path), corrupt_noi=True)
    with pytest.raises(ValueError, match=r"(?i)noi"):
        mod.parse_planilla(path)


def test_parse_source_metadata(fixture_xlsx):
    rows = mod.parse_planilla(fixture_xlsx)
    assert all(r["source_file"] == fixture_xlsx for r in rows)
    assert all(r["source_sheet"] == "Hoja1" for r in rows)
    assert all(isinstance(r["source_row"], int) and r["source_row"] > 0 for r in rows)


def test_file_hash_estable(fixture_xlsx):
    h1 = mod._file_hash(fixture_xlsx)
    h2 = mod._file_hash(fixture_xlsx)
    assert h1 == h2
    assert len(h1) == 64
