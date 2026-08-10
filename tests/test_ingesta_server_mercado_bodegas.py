"""Tests de los endpoints /api/mercado/bodegas/* de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_mercado_bodegas


@pytest.fixture
def texto_gps():
    from tests.db.test_ingest_mercado_bodegas import TEXTO_GPS_1S_2026
    return TEXTO_GPS_1S_2026


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_mercado_bodegas, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


def test_periodo_check_no_ingestado(client):
    res = client.get("/api/mercado/bodegas/periodo_check?periodo=2026-06")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


def test_validate_endpoint_ok(client, texto_gps):
    res = client.post("/api/mercado/bodegas/validate", json={
        "texto": texto_gps, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["n_filas"] == 6


def test_commit_endpoint_inserta_y_periodo_check_refleja(client, texto_gps):
    res = client.post("/api/mercado/bodegas/commit", json={
        "texto": texto_gps, "periodo": "2026-06",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["filas_insertadas"] == 6

    res2 = client.get("/api/mercado/bodegas/periodo_check?periodo=2026-06")
    assert res2.get_json()["ya_ingestado"] is True


def test_commit_endpoint_texto_invalido_retorna_400(client):
    res = client.post("/api/mercado/bodegas/commit", json={
        "texto": "esto no es una tabla", "periodo": "2026-06",
    })
    assert res.status_code == 400
    assert res.get_json()["ok"] is False
