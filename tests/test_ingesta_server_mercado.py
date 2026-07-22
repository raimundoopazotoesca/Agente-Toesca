"""Tests de los endpoints /api/mercado/* de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_mercado


@pytest.fixture
def texto_jll():
    from tests.db.test_ingest_mercado import TEXTO_JLL_Q3_2025
    return TEXTO_JLL_Q3_2025


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_mercado, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        yield c


def test_periodo_check_no_ingestado(client):
    res = client.get("/api/mercado/periodo_check?periodo=2025-09&proveedor=JLL")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


def test_validate_endpoint_ok(client, texto_jll):
    res = client.post("/api/mercado/validate", json={
        "texto": texto_jll, "periodo": "2025-09", "proveedor": "JLL",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["n_filas"] == 18


def test_validate_endpoint_texto_vacio(client):
    res = client.post("/api/mercado/validate", json={
        "texto": "", "periodo": "2025-09", "proveedor": "JLL",
    })
    data = res.get_json()
    assert data["ok"] is False


def test_commit_endpoint_inserta_y_periodo_check_refleja(client, texto_jll):
    res = client.post("/api/mercado/commit", json={
        "texto": texto_jll, "periodo": "2025-09", "proveedor": "JLL",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["filas_insertadas"] == 18

    res2 = client.get("/api/mercado/periodo_check?periodo=2025-09&proveedor=JLL")
    data2 = res2.get_json()
    assert data2["ya_ingestado"] is True
    assert data2["n_filas"] == 18


def test_commit_endpoint_texto_invalido_retorna_400(client):
    res = client.post("/api/mercado/commit", json={
        "texto": "esto no es una tabla", "periodo": "2025-09", "proveedor": "JLL",
    })
    assert res.status_code == 400
    assert res.get_json()["ok"] is False
