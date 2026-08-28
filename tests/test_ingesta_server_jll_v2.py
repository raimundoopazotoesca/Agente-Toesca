"""Tests de los endpoints /api/rentroll/* con el formato JLL v2.

Las rutas no cambian: el servidor detecta el formato por el contenido del
archivo y ramifica. Estos tests fijan que (a) el formato v2 no necesita que el
usuario declare un periodo, (b) el clasico sigue exigiendolo, y (c) el informe
de validate llega al front con errores y avisos separados.
"""
from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest

from tools.db.connection import apply_migrations, get_conn_for

RR_HEADER = [
    "portafolio", "fecha_corte_rent_roll", "piso", "local", "categoría_general",
    "#Contrato", "estado_rent_roll", "información_locatario_gla",
    "información_locatario_marca", "información_locatario_razón_social",
    "información_locatario_estado_contrato", "fechas_de_ocupación_inicio",
    "fechas_de_ocupación_fin", "renta_renta_real", "renta_m2",
]
AUX_HEADER = [
    "portafolio", "mes", "rubro_presupuestal", "clasificación presupuestal",
    "código_contable", "nombre_del_tercero", "descripción", "débito", "crédito",
]


def _planilla_v2(path: Path, estado="Ocupado") -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RentRoll"
    ws.append(RR_HEADER)
    ws.append(["Torre A", "2026-07-01", "PISO 1", "101", "OFICINA", "C1",
               estado, 100.0, "ACME", "ACME SPA", "Firmado", "2020-01-01",
               "2027-01-31", 60.0, 0.6])
    aux = wb.create_sheet("AuxiliarContable")
    aux.append(AUX_HEADER)
    aux.append(["Torre A", "2026-07-31", "Ingreso por arriendo", "Ingresos", 1,
                "ACME SPA", "Ingreso por arriendo", None, 60.0])
    wb.create_sheet("Cartera")
    wb.create_sheet("Recaudado")
    wb.save(path)
    return str(path)


def _upload(path: str):
    return {"file": (io.BytesIO(Path(path).read_bytes()), Path(path).name)}


@pytest.fixture
def client(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    conn.execute(
        "INSERT OR IGNORE INTO dim_activo (activo_key, nombre, fondo_key) "
        "VALUES ('Torre A', 'Torre A', 'PT')"
    )
    conn.commit()
    conn.close()

    from scripts import ingesta_server

    # El endpoint resuelve la DB como ROOT/memory/...; se apunta al temporal.
    monkeypatch.setattr(ingesta_server, "ROOT", tmp_path)
    (tmp_path / "memory").mkdir(exist_ok=True)
    Path(tmp_db_path).replace(tmp_path / "memory" / "agente_toesca_v2.db")
    # El rebuild del factsheet no es parte de lo que se prueba aca.
    monkeypatch.setattr(ingesta_server, "_rebuild_factsheet", lambda: None)

    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        c.environ_base["HTTP_X_INGESTA_TOKEN"] = ingesta_server.API_TOKEN
        yield c


def test_validate_v2_no_exige_periodo_y_lo_declara_el_archivo(client, tmp_path):
    path = _planilla_v2(tmp_path / "v2.xlsx")
    res = client.post("/api/rentroll/validate", data=_upload(path),
                      content_type="multipart/form-data")
    assert res.status_code == 200
    data = res.get_json()
    assert data["formato"] == "jll_v2"
    # el periodo sale del contenido, no del formulario
    assert data["periodos"] == ["2026-07"]
    assert data["ok"] is True


def test_validate_v2_separa_errores_de_avisos(client, tmp_path):
    """Un estado invalido bloquea; un rubro sin mapping solo avisa."""
    path = _planilla_v2(tmp_path / "malo.xlsx", estado="BS4B07")
    res = client.post("/api/rentroll/validate", data=_upload(path),
                      content_type="multipart/form-data")
    data = res.get_json()
    assert data["ok"] is False
    assert any("estado_invalido" in e for e in data["errors"])


def test_commit_v2_carga_sin_periodo(client, tmp_path):
    path = _planilla_v2(tmp_path / "ok.xlsx")
    res = client.post("/api/rentroll/commit", data=_upload(path),
                      content_type="multipart/form-data")
    assert res.status_code == 200, res.get_json()
    data = res.get_json()
    assert data["ok"] is True
    assert data["formato"] == "jll_v2"
    assert data["periodos"] == ["2026-07"]


def test_commit_v2_es_idempotente_por_endpoint(client, tmp_path):
    path = _planilla_v2(tmp_path / "dup.xlsx")
    client.post("/api/rentroll/commit", data=_upload(path),
                content_type="multipart/form-data")
    res = client.post("/api/rentroll/commit", data=_upload(path),
                      content_type="multipart/form-data")
    assert res.get_json()["status"] == "skipped_duplicate"


def test_formato_clasico_sigue_exigiendo_periodo(client, tmp_path):
    """Un archivo que no es v2 conserva el contrato anterior."""
    wb = openpyxl.Workbook()
    wb.active.append(["Arrendatario"])
    otro = tmp_path / "clasico.xlsx"
    wb.save(otro)

    res = client.post("/api/rentroll/validate", data=_upload(str(otro)),
                      content_type="multipart/form-data")
    data = res.get_json()
    assert data["ok"] is False
    assert any("período" in e or "periodo" in e for e in data["errors"])


def test_sin_archivo_falla_claro(client):
    res = client.post("/api/rentroll/validate", data={},
                      content_type="multipart/form-data")
    assert res.get_json()["ok"] is False
