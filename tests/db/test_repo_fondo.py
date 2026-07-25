"""Tests del repo de dimensiones (fondos, activos, series, cuentas)."""
import pytest

from tools.db import repo_fondo
from tools.db.errors import NotFoundError


def test_list_fondos(tmp_db):
    fondos = repo_fondo.list_fondos(tmp_db)
    keys = [f["fondo_key"] for f in fondos]
    assert keys == ["Apo", "PT", "TRI"]


def test_get_fondo(tmp_db):
    f = repo_fondo.get_fondo(tmp_db, "PT")
    assert f["nombre"] == "Fondo Toesca Rentas Inmobiliarias PT"


def test_get_fondo_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_fondo.get_fondo(tmp_db, "NO_EXISTE")


def test_list_activos_de_fondo(tmp_db):
    activos = repo_fondo.list_activos(tmp_db, fondo_key="TRI")
    keys = sorted(a["activo_key"] for a in activos)
    assert {"Apo3001", "INMOSA", "Mall Curicó", "Sucden", "Viña Centro"} <= set(keys)


def test_list_series_de_fondo(tmp_db):
    series = repo_fondo.list_series(tmp_db, fondo_key="TRI")
    keys = sorted(s["nemotecnico"] for s in series)
    assert keys == ["CFITOERI1A", "CFITOERI1C", "CFITOERI1I"]
