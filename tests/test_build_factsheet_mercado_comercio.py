"""Test para _fetch_mercado_comercio en scripts/build_factsheet.py."""
from __future__ import annotations

import sqlite3

import pytest

from scripts.build_factsheet import _fetch_mercado_comercio
from tools.db.connection import apply_migrations
from tools.db import ingest_mercado_comercio


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    ingest_mercado_comercio.DB_PATH = db_path
    ingest_mercado_comercio.commit("-0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%", "2026-06")
    return db_path


def test_fetch_mercado_comercio_periodo_existente(db):
    fila = _fetch_mercado_comercio(db, "2026-06")
    assert fila is not None
    assert fila["Total Comercio"] == pytest.approx(-0.009)
    assert fila["Supermercados"] == pytest.approx(-0.012)


def test_fetch_mercado_comercio_periodo_inexistente(db):
    assert _fetch_mercado_comercio(db, "2020-01") is None
