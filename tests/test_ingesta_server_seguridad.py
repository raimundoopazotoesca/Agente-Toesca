"""Tests de los controles de seguridad de scripts/ingesta_server.py.

El servidor expone la DB completa: lectura vía /api/chat y escritura vía
/api/*/commit. Escucha en loopback, donde cualquier proceso local —o una página
abierta en el mismo navegador— puede alcanzarlo.
"""
from __future__ import annotations

import io

import pytest

from scripts import ingesta_server


@pytest.fixture
def app():
    ingesta_server.app.config["TESTING"] = True
    return ingesta_server.app


@pytest.fixture
def anon(app):
    """Cliente sin token."""
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth(app):
    """Cliente con el token de la sesión."""
    with app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


# ── Autenticación ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/api/estado_ingesta"),
    ("get", "/api/eeff/periodo_check?fondo=APO&periodo=2026-03"),
    ("post", "/api/chat"),
    ("post", "/api/validate"),
    ("post", "/api/ingest"),
    ("post", "/api/rentroll/commit"),
    ("post", "/api/mercado/commit"),
    ("post", "/api/balance/commit"),
    ("post", "/api/parking/commit"),
])
def test_api_sin_token_es_401(anon, metodo, ruta):
    res = getattr(anon, metodo)(ruta)
    assert res.status_code == 401, f"{ruta} quedó accesible sin token"


def test_token_incorrecto_es_401(anon):
    res = anon.get("/api/estado_ingesta", headers={"X-Ingesta-Token": "no-es-el-token"})
    assert res.status_code == 401


def test_token_correcto_pasa(auth):
    res = auth.get("/api/estado_ingesta")
    assert res.status_code == 200


def test_paginas_html_no_exigen_token(anon):
    """La página debe cargar sin token: es la que lo recibe inyectado."""
    assert anon.get("/ingesta").status_code == 200


def test_pagina_ingesta_inyecta_el_token(anon):
    html = anon.get("/ingesta").get_data(as_text=True)
    assert ingesta_server.API_TOKEN in html
    assert "INGESTA_TOKEN" in html


# ── CORS ─────────────────────────────────────────────────────────────────────

def test_cors_no_refleja_origen_arbitrario(auth):
    res = auth.get("/api/estado_ingesta", headers={"Origin": "https://sitio-malicioso.example"})
    assert res.headers.get("Access-Control-Allow-Origin") is None


def test_cors_rechaza_origen_null(auth):
    """file:// manda Origin: null; antes se reflejaba y permitía exfiltrar datos."""
    res = auth.get("/api/estado_ingesta", headers={"Origin": "null"})
    assert res.headers.get("Access-Control-Allow-Origin") is None


def test_cors_permite_localhost(auth):
    res = auth.get("/api/estado_ingesta", headers={"Origin": "http://127.0.0.1:8765"})
    assert res.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"


# ── Límites y manejo de errores ──────────────────────────────────────────────

def test_hay_limite_de_tamano_de_subida(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 32 * 1024 * 1024


def test_subida_demasiado_grande_es_413_con_json(auth, app):
    grande = b"x" * (app.config["MAX_CONTENT_LENGTH"] + 1024)
    res = auth.post(
        "/api/rentroll/validate",
        data={"file": (io.BytesIO(grande), "enorme.xlsx"), "periodo": "2026-05"},
        content_type="multipart/form-data",
    )
    assert res.status_code == 413
    assert res.get_json()["ok"] is False


def test_xlsx_corrupto_da_error_legible_no_500(auth):
    """Un archivo de proveedor ilegible es error del archivo, no un bug: 400/200
    con mensaje, nunca un 500 con traceback de Werkzeug."""
    basura = io.BytesIO(b"esto no es un xlsx")
    res = auth.post(
        "/api/rentroll/validate",
        data={"file": (basura, "roto.xlsx"), "periodo": "2026-05"},
        content_type="multipart/form-data",
    )
    assert res.status_code != 500
    body = res.get_json()
    assert body["ok"] is False
    assert body["errors"], "debe explicar por qué no se pudo leer"


def test_debug_apagado():
    """El debugger de Werkzeug expone una consola interactiva."""
    assert ingesta_server.app.debug is False
