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


def test_estado_ingesta_endpoint_devuelve_3_tipos(client):
    res = client.get("/api/estado_ingesta")
    assert res.status_code == 200
    data = res.get_json()
    ids = {t["id"] for t in data["tipos"]}
    assert ids == {"eeff", "rentroll", "mercado"}
    for tipo in data["tipos"]:
        assert "ultimo_ingestado" in tipo
        assert "pendiente" in tipo
        assert "al_dia" in tipo
        assert "timeline" in tipo
        assert "tab_destino" in tipo
