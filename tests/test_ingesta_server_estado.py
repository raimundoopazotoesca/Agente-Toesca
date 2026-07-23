"""Tests del endpoint /api/estado_ingesta de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import estado_ingesta


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(estado_ingesta, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        yield c


def test_estado_ingesta_endpoint_devuelve_tipos(client):
    res = client.get("/api/estado_ingesta")
    assert res.status_code == 200
    data = res.get_json()
    ids = {t["id"] for t in data["tipos"]}
    assert ids == {"eeff", "rentroll", "mercado", "balance", "parking_pt"}
    for tipo in data["tipos"]:
        assert "ultimo_ingestado" in tipo
        assert "pendiente" in tipo
        assert "al_dia" in tipo
        assert "timeline" in tipo
        assert "tab_destino" in tipo


def test_timeline_range_endpoint_devuelve_rango_completo(client):
    res = client.get("/api/estado_ingesta/timeline_range?tipo=eeff&offset_min=-8&offset_max=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["id"] == "eeff"
    assert data["n"] == 4
    assert len(data["periodos"]) == (1 - (-8) + 4)  # offset_max - offset_min + n
    assert len(data["sub_ingestas"]) == 3
    assert len(data["sub_ingestas"][0]["periodos"]) == len(data["periodos"])


def test_timeline_range_endpoint_defaults(client):
    res = client.get("/api/estado_ingesta/timeline_range?tipo=rentroll")
    assert res.status_code == 200
    data = res.get_json()
    assert data["offset_min"] == -8
    assert data["offset_max"] == 1


def test_timeline_range_endpoint_tipo_invalido(client):
    res = client.get("/api/estado_ingesta/timeline_range?tipo=no_existe")
    assert res.status_code == 400


def test_timeline_range_endpoint_offset_invalido(client):
    res = client.get("/api/estado_ingesta/timeline_range?tipo=eeff&offset_min=abc")
    assert res.status_code == 400


def test_timeline_range_endpoint_offset_min_mayor_que_max(client):
    res = client.get("/api/estado_ingesta/timeline_range?tipo=eeff&offset_min=5&offset_max=-5")
    assert res.status_code == 400
