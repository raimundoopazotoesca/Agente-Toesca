"""Tests para tools.db.ingest_dolar."""
from __future__ import annotations

from tools.db import ingest_dolar as mod
from tools.db import repo_fact


def test_backfill_dolar_hoy_upsertea(tmp_db, monkeypatch):
    monkeypatch.setattr(mod, "fetch_dolar_hoy", lambda: ("2026-07-27", 942.7))
    rep = mod.backfill_dolar_hoy(conn=tmp_db, verbose=False)
    assert rep == {"archivos": 1, "filas": 1, "sin_datos": []}
    assert repo_fact.get_dolar(tmp_db, "2026-07-27") == 942.7


def test_backfill_dolar_hoy_reporta_error_de_red_sin_lanzar(tmp_db, monkeypatch):
    def _boom():
        raise TimeoutError("sin conexión")
    monkeypatch.setattr(mod, "fetch_dolar_hoy", _boom)
    rep = mod.backfill_dolar_hoy(conn=tmp_db, verbose=False)
    assert rep["archivos"] == 0
    assert rep["filas"] == 0
    assert "sin conexión" in rep["sin_datos"][0]
