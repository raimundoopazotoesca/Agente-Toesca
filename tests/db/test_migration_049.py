"""Validación post-migración 049: schema, seeds y vista de look-through."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.db.connection import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "tools" / "db" / "migrations"


@pytest.fixture
def db(tmp_path):
    """DB temporal con todas las migraciones aplicadas."""
    path = tmp_path / "test.db"
    apply_migrations(str(path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_dim_sociedad_existe_y_tiene_7_filas(db):
    rows = db.execute(
        "SELECT sociedad_key, fondo_key, participacion_fondo_en_sociedad "
        "FROM dim_sociedad ORDER BY sociedad_key"
    ).fetchall()
    assert len(rows) == 7
    keys = {r["sociedad_key"] for r in rows}
    assert keys == {
        "ApoquindoSpA", "BlvdSpA", "Chanarcillo", "CuricoSpA",
        "SeniorAssist", "TorreASA", "VCSpA",
    }


def test_dim_sociedad_participaciones(db):
    got = {
        r["sociedad_key"]: (r["fondo_key"], r["participacion_fondo_en_sociedad"])
        for r in db.execute("SELECT * FROM dim_sociedad")
    }
    assert got["Chanarcillo"] == ("TRI", 1.0)
    assert got["CuricoSpA"] == ("TRI", 0.80)
    assert got["SeniorAssist"] == ("TRI", 0.43)
    assert got["VCSpA"] == ("TRI", 1.0)
    assert got["TorreASA"] == ("PT", 1.0)
    assert got["BlvdSpA"] == ("PT", 1.0)
    assert got["ApoquindoSpA"] == ("Apo", 1.0)


def test_dim_activo_sociedad_key_poblado(db):
    esperado = {
        "Sucden": ("Chanarcillo", 1.0),
        "Apo3001": ("Chanarcillo", 0.685),
        "Viña Centro": ("VCSpA", 1.0),
        "Mall Curicó": ("CuricoSpA", 1.0),
        "INMOSA": ("SeniorAssist", 1.0),
        "Torre A": ("TorreASA", 1.0),
        "Boulevard": ("BlvdSpA", 1.0),
        "Apo4501": ("ApoquindoSpA", 1.0),
        "Apo4700": ("ApoquindoSpA", 1.0),
    }
    rows = db.execute(
        "SELECT activo_key, sociedad_key, participacion_en_sociedad "
        "FROM dim_activo WHERE sociedad_key IS NOT NULL"
    ).fetchall()
    got = {r["activo_key"]: (r["sociedad_key"], r["participacion_en_sociedad"]) for r in rows}
    for act, expected in esperado.items():
        assert act in got, f"activo {act} no tiene sociedad_key poblado"
        s_got, p_got = got[act]
        assert s_got == expected[0], f"{act}: sociedad_key {s_got} != {expected[0]}"
        assert abs(p_got - expected[1]) < 1e-9, f"{act}: part {p_got} != {expected[1]}"


def test_dim_fondo_padre_poblado(db):
    rows = {r["fondo_key"]: (r["fondo_padre"], r["participacion_en_padre"])
            for r in db.execute("SELECT * FROM dim_fondo")}
    assert rows["PT"] == ("TRI", 0.333)
    assert rows["Apo"] == ("TRI", 0.30)
    assert rows["TRI"] == (None, None)


def test_vista_lookthrough_13_filas(db):
    n = db.execute("SELECT COUNT(*) FROM v_activo_fondo_efectivo").fetchone()[0]
    assert n == 13, f"esperaba 13 filas, hay {n}"


def test_vista_lookthrough_directas(db):
    rows = db.execute(
        "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo "
        "WHERE fondo_key='TRI' AND via='directa' ORDER BY activo_key"
    ).fetchall()
    got = {r["activo_key"]: round(r["participacion_efectiva"], 6) for r in rows}
    assert got == {
        "Apo3001": 0.685,
        "INMOSA": 0.43,
        "Mall Curicó": 0.80,
        "Sucden": 1.0,
        "Viña Centro": 1.0,
    }


def test_vista_lookthrough_via_padre(db):
    rows = db.execute(
        "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo "
        "WHERE fondo_key='TRI' AND via='lookthrough' ORDER BY activo_key"
    ).fetchall()
    got = {r["activo_key"]: round(r["participacion_efectiva"], 6) for r in rows}
    assert got == {
        "Apo4501": 0.30,
        "Apo4700": 0.30,
        "Boulevard": 0.333,
        "Torre A": 0.333,
    }


def test_vieja_participacion_fondo_activo_intacta(db):
    """La columna vieja no se toca. Valores conocidos permanecen."""
    got = {r["activo_key"]: r["participacion_fondo_activo"]
           for r in db.execute("SELECT activo_key, participacion_fondo_activo FROM dim_activo")}
    assert got.get("Apo4501") == 1.0
    assert got.get("Apo4700") == 1.0
    assert got.get("Torre A") == 0.333
    assert got.get("Boulevard") == 0.333
    assert got.get("INMOSA") == 0.43
