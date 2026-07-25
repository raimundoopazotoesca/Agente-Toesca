"""Tests de los endpoints EEFF de scripts/ingesta_server.py.

Este path no tenía cobertura y por eso un NameError (`existing_hash`) lo dejó
roto ~4 días sin que nadie lo detectara: `validate()` construye `result.data`
para todo payload que pase los gates previos, y ni `/api/validate` ni
`/api/ingest` capturaban NameError.
"""
from __future__ import annotations

import json

import pytest

from tools.db.connection import apply_migrations, get_conn_for
from tools.db import ingest_eeff_validated as core


def _payload(periodo: str = "2026-03", fondo: str = "APO", **extra) -> dict:
    """Payload EEFF mínimo válido, con la suma de gastos cuadrada."""
    base = {
        "fondo": fondo,
        "prompt_version": "eeff-v1",
        "periodos_reportados": [periodo],
        "en_miles_pesos": False,
        "lineas": [
            {"section": "ESF", "cuenta_codigo": "ESF.total_activo",
             "cuenta_nombre": "Total activo", "periodo": periodo, "monto_clp": 1_000_000},
            {"section": "ER", "cuenta_codigo": "ER.depreciaciones",
             "cuenta_nombre": "Depreciaciones", "periodo": periodo, "monto_clp": -1000},
            {"section": "ER", "cuenta_codigo": "ER.otros_gastos",
             "cuenta_nombre": "Otros gastos", "periodo": periodo, "monto_clp": -2000},
            {"section": "ER", "cuenta_codigo": "ER.total_gastos_operacion",
             "cuenta_nombre": "Total gastos de operación", "periodo": periodo,
             "monto_clp": -3000},
        ],
    }
    base.update(extra)
    return base


def _texto(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    # Ya no hace falta sembrar dim_cuenta: el baseline (F0.2) eliminó esa tabla
    # obsoleta y su FK, que existían solo en la cadena de migraciones y hacían
    # fallar toda ingesta con cuenta_codigo en una DB nueva.
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(core, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    monkeypatch.setattr(ingesta_server, "_rebuild_factsheet", lambda: None)
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        # Todo /api/* exige el token; el servidor lo inyecta en las páginas que
        # sirve. Aquí se manda en todas las requests del cliente de prueba.
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


# ── periodo_check ────────────────────────────────────────────────────────────

def test_periodo_check_sin_datos(client):
    res = client.get("/api/eeff/periodo_check?fondo=APO&periodo=2026-03")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


def test_periodo_check_sin_parametros_no_revienta(client):
    res = client.get("/api/eeff/periodo_check")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


# ── validate ─────────────────────────────────────────────────────────────────

def test_validate_payload_valido(client):
    """Regresión del NameError: este payload llega a construir result.data."""
    res = client.post("/api/validate", json={"fondo": "APO", "texto": _texto(_payload()), "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True, data.get("errors")
    assert data["fondo"] == "APO"
    assert data["periodos"] == ["2026-03"]
    assert data["n_lineas"] == 4
    assert data["ya_ingestado"] is False
    assert data["file_hash"]


def test_validate_expone_cuadratura_de_gastos(client):
    res = client.post("/api/validate", json={"fondo": "APO", "texto": _texto(_payload()), "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    gastos = res.get_json()["gastos_por_periodo"]["2026-03"]
    assert gastos["cuadra"] is True
    assert gastos["suma_componentes"] == -3000
    assert gastos["total_reportado"] == -3000


def test_validate_detecta_descuadre_de_gastos(client):
    """La cuadratura se recalcula server-side; no se confía en el LLM."""
    payload = _payload()
    payload["lineas"][1]["monto_clp"] = -999_999
    res = client.post("/api/validate", json={"fondo": "APO", "texto": _texto(payload), "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    data = res.get_json()
    assert data["ok"] is False
    assert any("cuadra" in e.lower() or "gastos" in e.lower() for e in data["errors"])


def test_validate_rechaza_fondo_cruzado(client):
    res = client.post("/api/validate", json={"fondo": "PT", "texto": _texto(_payload(fondo="APO")), "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    data = res.get_json()
    assert data["ok"] is False
    assert any("fondo" in e.lower() for e in data["errors"])


def test_validate_rechaza_prompt_version_desconocida(client):
    """Detecta prompt-drift silencioso."""
    res = client.post("/api/validate", json={
        "fondo": "APO", "texto": _texto(_payload(prompt_version="eeff-v99")),
        "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30",
    })
    data = res.get_json()
    assert data["ok"] is False
    assert any("prompt_version" in e for e in data["errors"])


def test_validate_texto_vacio(client):
    res = client.post("/api/validate", json={"fondo": "APO", "texto": "   ", "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    data = res.get_json()
    assert data["ok"] is False


def test_validate_json_invalido_no_revienta(client):
    res = client.post("/api/validate", json={"fondo": "APO", "texto": "esto no es JSON", "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is False


# ── ingest (commit) ──────────────────────────────────────────────────────────

def test_ingest_persiste_y_periodo_check_lo_refleja(client, tmp_db_path):
    res = client.post("/api/ingest", json={"fondo": "APO", "texto": _texto(_payload()), "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["ok"] is True
    assert body["rows_eeff"] == 4

    con = get_conn_for(tmp_db_path)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_eeff_line WHERE fondo_key='Apo' AND periodo='2026-03'"
        ).fetchone()[0]
        alias = con.execute(
            "SELECT COUNT(*) FROM raw_eeff_line WHERE fondo_key='APO'"
        ).fetchone()[0]
        run = con.execute(
            "SELECT tool, status FROM ingest_run ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    assert n == 4, "debe persistir la clave canónica 'Apo'"
    assert alias == 0, "no debe persistir el alias de entrada 'APO'"
    assert run[0] == "ingest_eeff_validated"

    res2 = client.get("/api/eeff/periodo_check?fondo=APO&periodo=2026-03")
    assert res2.get_json() == {"ya_ingestado": True, "n_filas": 4}


def test_ingest_mismo_texto_dos_veces_no_duplica(client):
    """Idempotencia por file_hash: el segundo intento se bloquea por período."""
    texto = _texto(_payload())
    assert client.post("/api/ingest", json={"fondo": "APO", "texto": texto, "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"}).status_code == 200

    res = client.post("/api/ingest", json={"fondo": "APO", "texto": texto, "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_ingest_periodo_ya_cargado_retorna_400(client):
    """Otro archivo (hash distinto) para un período ya cargado también se bloquea."""
    assert client.post(
        "/api/ingest", json={"fondo": "APO", "texto": _texto(_payload()), "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"}
    ).status_code == 200

    otro = _payload()
    otro["lineas"][0]["monto_clp"] = 2_000_000  # cambia el hash, mismo período
    res = client.post("/api/ingest", json={"fondo": "APO", "texto": _texto(otro), "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    assert res.status_code == 400
    assert "Ya existen datos ingestados" in res.get_json()["error"]


def test_ingest_payload_invalido_retorna_400_no_500(client):
    res = client.post("/api/ingest", json={"fondo": "APO", "texto": "no soy JSON", "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_validate_marca_ya_ingestado_tras_commit(client):
    """`ya_ingestado` refleja el file_hash en DB (mismo criterio que
    skipped_duplicate de commit), no la ocupación del período."""
    texto = _texto(_payload())
    client.post("/api/ingest", json={"fondo": "APO", "texto": texto, "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"})

    data = client.post("/api/validate", json={"fondo": "APO", "texto": texto, "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30"}).get_json()
    assert data["ya_ingestado"] is True
    assert data["periodos_existentes"] == {"2026-03": 4}


def test_ingest_apo_persiste_clave_canonica(client, tmp_db_path):
    """`APO` es alias de entrada (lo usan el prompt y la UI); la clave canónica
    de dim_fondo es `Apo`. Insertar el alias viola la FK
    raw_eeff_line.fondo_key -> dim_fondo(fondo_key)."""
    res = client.post("/api/ingest", json={
        "fondo": "APO", "texto": _texto(_payload()),
        "periodo_declarado": "2026-03", "fecha_publicacion": "2026-05-30",
    })
    assert res.status_code == 200, res.get_json()

    con = get_conn_for(tmp_db_path)
    try:
        claves = [r[0] for r in con.execute("SELECT DISTINCT fondo_key FROM raw_eeff_line")]
    finally:
        con.close()
    assert claves == ["Apo"]


def test_periodo_check_encuentra_historico_con_alias(client, tmp_db_path):
    """Las lecturas usan UPPER() para no perder de vista el histórico cargado
    como 'APO' mientras la consolidación de datos (F0.3) no se ejecute."""
    con = get_conn_for(tmp_db_path)
    try:
        con.execute("PRAGMA foreign_keys=OFF")  # simula el histórico ya existente
        con.execute(
            "INSERT INTO raw_eeff_line (fondo_key, periodo, cuenta_nombre, monto_clp, file_hash) "
            "VALUES ('APO','2025-12','Total activo',1,'hist')"
        )
        con.commit()
    finally:
        con.close()

    assert core._periodos_existentes("Apo", ["2025-12"]) == {"2025-12": 1}
    assert core._periodos_existentes("APO", ["2025-12"]) == {"2025-12": 1}
