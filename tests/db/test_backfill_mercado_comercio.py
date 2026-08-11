"""Tests para tools.db.backfill_mercado_comercio."""
from __future__ import annotations

import openpyxl
import pytest

from tools.db import backfill_mercado_comercio as mod
from tools.db.connection import apply_migrations, get_conn_for


@pytest.fixture
def xlsx_fixture(tmp_path):
    """Excel mínimo con la misma estructura que el histórico real del
    usuario: encabezado en la fila 5, datos desde la fila 6, columnas
    Mes/Período acumulado/7 categorías/Fuente/Referencia."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Histórico publicado"
    ws.append(["CNC — Variaciones reales acumuladas | Total Locales RM"])
    ws.append(["nota"])
    ws.append(["nota 2"])
    ws.append([])
    ws.append([
        "Mes", "Período acumulado", "Total Comercio", "Vestuario", "Calzado",
        "Artefactos Eléctricos", "Línea Hogar", "Muebles",
        "Supermercado Tradicional", "Fuente CNC", "Referencia exacta",
    ])
    ws.append([
        "2025-03-01", "Mar. 2025/2024", 0.01, 0.047, -0.012, 0.065, 0.087,
        -0.017, -0.02, "https://example.com", "p. 4",
    ])
    ws.append([
        "2025-04-01", "Abr. 2025/2024", 0.018, 0.067, -0.01, 0.044, 0.089,
        -0.034, -0.008, "https://example.com", "p. 4",
    ])
    path = tmp_path / "cnc_fixture.xlsx"
    wb.save(path)
    return str(path)


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    return db_path


def test_backfill_inserta_18x7_filas(xlsx_fixture, db):
    result = mod.backfill(xlsx_fixture, db_path=db)
    assert result["status"] == "ok"
    assert result["filas_insertadas"] == 2 * 7
    assert result["periodos"] == ["2025-03", "2025-04"]

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE superseded_at IS NULL"
    ).fetchone()[0]
    supermercados_mar = con.execute(
        "SELECT variacion_acumulada_pct FROM raw_mercado_comercio "
        "WHERE periodo='2025-03' AND categoria='Supermercados'"
    ).fetchone()[0]
    con.close()
    assert n == 14
    assert supermercados_mar == pytest.approx(-0.02)


def test_backfill_es_idempotente(xlsx_fixture, db):
    mod.backfill(xlsx_fixture, db_path=db)
    result2 = mod.backfill(xlsx_fixture, db_path=db)
    assert result2["filas_insertadas"] == 0

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert n == 14
