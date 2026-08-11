"""Tests para tools.db.ingest_mercado_comercio."""
from __future__ import annotations

import pytest

from tools.db import ingest_mercado_comercio as mod
from tools.db.connection import apply_migrations, get_conn_for

# Fila real: Junio 2026/2025 (última fila del Excel histórico del usuario).
# Orden: Total Comercio, Vestuario, Calzado, Artefactos Eléctricos,
# Línea Hogar, Muebles, Supermercado Tradicional.
TEXTO_JUN_2026 = "-0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%"


def test_parse_fila_comercio_ok():
    fila = mod.parse_fila_comercio(TEXTO_JUN_2026)
    assert fila["Total Comercio"] == pytest.approx(-0.009)
    assert fila["Vestuario"] == pytest.approx(0.062)
    assert fila["Calzado"] == pytest.approx(-0.03)
    assert fila["Artefactos Eléctricos"] == pytest.approx(-0.091)
    assert fila["Línea Hogar"] == pytest.approx(0.002)
    assert fila["Muebles"] == pytest.approx(-0.006)
    assert fila["Supermercados"] == pytest.approx(-0.012)


def test_parse_fila_comercio_con_encabezado_y_guion():
    texto = (
        "Total Comercio Vestuario Calzado Artefactos Eléctricos Línea Hogar Muebles Supermercado Tradicional\n"
        "0,7% 4,0% -4,5% 0,3% 5,3% -3,6% -0,2%"
    )
    fila = mod.parse_fila_comercio(texto)
    assert fila["Total Comercio"] == pytest.approx(0.007)
    assert fila["Supermercados"] == pytest.approx(-0.002)


def test_parse_fila_comercio_valor_faltante_como_guion():
    texto = "0,7% 4,0% -4,5% 0,3% 5,3% - -0,2%"
    fila = mod.parse_fila_comercio(texto)
    assert fila["Muebles"] is None


def test_parse_fila_comercio_sin_fila_valida_retorna_none():
    assert mod.parse_fila_comercio("esto no es una tabla") is None


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    monkeypatch.setattr(mod, "DB_PATH", db_path)
    return db_path


def test_validate_sin_periodo():
    result = mod.validate(TEXTO_JUN_2026, "")
    assert not result.ok
    assert any("período" in e.lower() for e in result.errors)


def test_validate_texto_invalido():
    result = mod.validate("esto no es una tabla", "2026-06")
    assert not result.ok
    assert any("fila válida" in e for e in result.errors)


def test_validate_ok(db):
    result = mod.validate(TEXTO_JUN_2026, "2026-06")
    assert result.ok
    assert result.data["periodo"] == "2026-06"
    assert len(result.data["fila"]) == 7


def test_commit_inserta_filas(db):
    result = mod.commit(TEXTO_JUN_2026, "2026-06")
    assert result["status"] == "ok"
    assert result["filas_insertadas"] == 7
    assert result["filas_superseded"] == 0

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    supermercados = con.execute(
        "SELECT variacion_acumulada_pct FROM raw_mercado_comercio "
        "WHERE periodo='2026-06' AND categoria='Supermercados' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert n == 7
    assert supermercados == pytest.approx(-0.012)


def test_commit_idempotente_mismo_texto(db):
    mod.commit(TEXTO_JUN_2026, "2026-06")
    result2 = mod.commit(TEXTO_JUN_2026, "2026-06")
    assert result2["status"] == "skipped_duplicate"
    assert result2["filas_insertadas"] == 0


def test_commit_reemplaza_periodo_con_texto_distinto(db):
    mod.commit(TEXTO_JUN_2026, "2026-06")
    texto_v2 = TEXTO_JUN_2026.replace("-1,2%", "-1,5%")
    result2 = mod.commit(texto_v2, "2026-06")
    assert result2["status"] == "ok"
    assert result2["filas_superseded"] == 7

    con = get_conn_for(db)
    vigentes = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_comercio WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert vigentes == 7
