from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_amortizacion_extra


def _seed_credito(db_path, credito_key="TEST_CRED", estado="VIGENTE"):
    from tools.db.connection import get_conn_for
    con = get_conn_for(db_path)
    con.execute(
        "INSERT INTO dim_credito (credito_key, activo_key, fondo_key, acreedor, estado) "
        "VALUES (?, 'ActivoTest', 'TRI', 'BancoTest', ?)",
        (credito_key, estado),
    )
    con.commit()
    con.close()


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_amortizacion_extra, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


def test_creditos_endpoint_requiere_token(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_amortizacion_extra, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        res = c.get("/api/amort_extra/creditos")  # sin header de token
    assert res.status_code == 401


def test_creditos_endpoint_lista_solo_vigentes(client, tmp_db_path):
    _seed_credito(tmp_db_path, credito_key="V1", estado="VIGENTE")
    _seed_credito(tmp_db_path, credito_key="P1", estado="PAGADO")

    res = client.get("/api/amort_extra/creditos")

    assert res.status_code == 200
    keys = {c["credito_key"] for c in res.get_json()["creditos"]}
    assert "V1" in keys
    assert "P1" not in keys


def test_commit_endpoint_persiste_evento(client, tmp_db_path):
    _seed_credito(tmp_db_path, credito_key="TEST_CRED")

    res = client.post(
        "/api/amort_extra/commit",
        json={"credito_key": "TEST_CRED", "fecha": "2026-08-15", "monto_uf": 100.0, "nota": "test"},
    )

    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["periodo"] == "2026-08"

    hist_res = client.get("/api/amort_extra/historial?credito_key=TEST_CRED")
    eventos = hist_res.get_json()["eventos"]
    assert len(eventos) == 1
    assert eventos[0]["nota"] == "test"


def test_commit_endpoint_rechaza_credito_pagado(client, tmp_db_path):
    _seed_credito(tmp_db_path, credito_key="PAGADO_CRED", estado="PAGADO")

    res = client.post(
        "/api/amort_extra/commit",
        json={"credito_key": "PAGADO_CRED", "fecha": "2026-08-15", "monto_uf": 100.0},
    )

    assert res.status_code == 400
    assert res.get_json()["ok"] is False
