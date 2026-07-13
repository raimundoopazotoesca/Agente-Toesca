"""Tests de las query tools sobre la DB (Fase 4)."""
import tools.query_tools as q
from tools.db import repo_audit, repo_kpi, repo_fact, repo_rent_roll, repo_er_activo, repo_flujo
from tools.db.connection import apply_migrations, get_conn_for


def _patch_conn(monkeypatch, tmp_db_path):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(q, "get_conn", lambda: get_conn_for(tmp_db_path))


def test_kpi_vacio(tmp_db_path, monkeypatch):
    _patch_conn(monkeypatch, tmp_db_path)
    out = q.consultar_db_kpi("activo", "PT", "NOI")
    assert "Sin datos" in out


def test_kpi_con_datos(tmp_db_path, monkeypatch):
    _patch_conn(monkeypatch, tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    repo_kpi.upsert(conn, "fondo", "PT", "2026-02", "valor_cuota_libro", 100.0, "CLP", "eeff_pdf_v1")
    repo_kpi.upsert(conn, "fondo", "PT", "2026-03", "valor_cuota_libro", 110.0, "CLP", "eeff_pdf_v1")
    conn.close()

    out = q.consultar_db_kpi("fondo", "PT", "valor_cuota_libro")
    assert "2026-02" in out and "2026-03" in out
    assert "10.00%" in out  # variación +10%


def test_precio_mas_reciente(tmp_db_path, monkeypatch):
    _patch_conn(monkeypatch, tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    repo_fact.upsert_precio(conn, "CFITRIPT-E", "2026-03-31", 1500.0, "LarraínVial")
    conn.close()

    out = q.consultar_db_precio("cfitript-e")
    assert "1,500" in out and "2026-03-31" in out


def test_rent_roll(tmp_db_path, monkeypatch):
    _patch_conn(monkeypatch, tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    rid = repo_audit.start_ingest_run(conn, tool="t", source_file=None, file_hash="H")
    repo_rent_roll.insert_lines(conn, [
        {"activo_key": "PT", "periodo": "2026-03", "unidad": "1001",
         "arrendatario": "Acme", "m2": 100.0, "renta_uf": 0.5, "source_row": 1, "file_hash": "H"},
    ], rid)
    conn.close()

    out = q.consultar_db_rent_roll("PT", "2026-03")
    assert "Acme" in out and "1001" in out


def test_cobertura(tmp_db_path, monkeypatch):
    import json

    _patch_conn(monkeypatch, tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    repo_fact.upsert_uf(conn, "2026-03-31", 38000.0)
    conn.close()

    out = json.loads(q.consultar_db_cobertura())
    assert out["raw_uf_diaria"]["total_filas"] == 1
    assert out["raw_rent_roll_line"]["total_filas"] == 0


def test_er_y_flujo_vacios(tmp_db_path, monkeypatch):
    _patch_conn(monkeypatch, tmp_db_path)
    assert "Sin ER" in q.consultar_db_er("Viña Centro", "2026-03")
    assert "Sin flujo" in q.consultar_db_flujo("INMOSA", "2026-03")
