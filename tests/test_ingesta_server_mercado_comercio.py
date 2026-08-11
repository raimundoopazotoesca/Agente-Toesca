"""Tests de los endpoints /api/mercado/comercio/* de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_mercado_comercio

TEXTO_JUN_2026 = "-0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%"


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_mercado_comercio, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


def test_periodo_check_no_ingestado(client):
    res = client.get("/api/mercado/comercio/periodo_check?periodo=2026-06")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


def test_validate_endpoint_ok(client):
    res = client.post("/api/mercado/comercio/validate", json={
        "texto": TEXTO_JUN_2026, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True


def test_commit_endpoint_inserta_y_periodo_check_refleja(client):
    res = client.post("/api/mercado/comercio/commit", json={
        "texto": TEXTO_JUN_2026, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["filas_insertadas"] == 7

    res2 = client.get("/api/mercado/comercio/periodo_check?periodo=2026-06")
    assert res2.get_json()["ya_ingestado"] is True


def test_commit_endpoint_texto_invalido_retorna_400(client):
    res = client.post("/api/mercado/comercio/commit", json={
        "texto": "esto no es una tabla", "periodo": "2026-06",
    })
    assert res.status_code == 400
    assert res.get_json()["ok"] is False
