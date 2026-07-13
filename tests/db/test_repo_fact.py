"""Tests de repo_fact."""
import pytest

from tools.db import repo_fact
from tools.db.errors import NotFoundError


def test_upsert_precio_cuota(tmp_db):
    repo_fact.upsert_precio(tmp_db, nemotecnico="CFITRIPT-E", fecha="2026-04-30", precio=1234.5, fuente="bolsa")
    row = repo_fact.get_precio(tmp_db, "CFITRIPT-E", "2026-04-30")
    assert row["precio"] == 1234.5


def test_upsert_precio_sobrescribe(tmp_db):
    repo_fact.upsert_precio(tmp_db, nemotecnico="CFITRIPT-E", fecha="2026-04-30", precio=1.0)
    repo_fact.upsert_precio(tmp_db, nemotecnico="CFITRIPT-E", fecha="2026-04-30", precio=2.0)
    row = repo_fact.get_precio(tmp_db, "CFITRIPT-E", "2026-04-30")
    assert row["precio"] == 2.0


def test_get_precio_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_fact.get_precio(tmp_db, "CFITRIPT-E", "1999-01-01")


def test_upsert_uf(tmp_db):
    repo_fact.upsert_uf(tmp_db, fecha="2026-04-30", valor_clp=37500.0)
    assert repo_fact.get_uf(tmp_db, "2026-04-30") == 37500.0


def test_get_uf_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_fact.get_uf(tmp_db, "1999-01-01")


def test_upsert_dividendo(tmp_db):
    repo_fact.upsert_dividendo(tmp_db, nemotecnico="CFITOERI1A", fecha_pago="2026-05-15", monto=42.5)
    rows = repo_fact.list_dividendos(tmp_db, "CFITOERI1A")
    assert len(rows) == 1
    assert rows[0]["monto"] == 42.5


def test_upsert_dividendo_es_idempotente(tmp_db):
    repo_fact.upsert_dividendo(tmp_db, "CFITOERI1A", "2026-05-15", 42.5)
    repo_fact.upsert_dividendo(tmp_db, "CFITOERI1A", "2026-05-15", 50.0)
    rows = repo_fact.list_dividendos(tmp_db, "CFITOERI1A")
    assert len(rows) == 1
    assert rows[0]["monto"] == 50.0
