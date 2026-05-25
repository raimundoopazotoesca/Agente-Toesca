"""Tests del dual-write de precios a la DB (Fase 1)."""
import tools.web_bursatil_tools as wb
from tools.db import repo_fact
from tools.db.connection import apply_migrations, get_conn_for


def test_obtener_precio_persiste_en_db(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    # La conexión que usa el módulo apunta a la DB temporal de test.
    monkeypatch.setattr(wb, "get_conn", lambda: get_conn_for(tmp_db_path))
    # Evitar red: notación fija y datachart canónico.
    monkeypatch.setattr(wb, "_get_notation_id", lambda nemo: "1")
    monkeypatch.setattr(
        wb,
        "_fetch",
        lambda url, timeout=10: "x:[{date:new Date(2026,3,30,0,0,0),close:1234.5,volume:0}]",
    )

    out = wb.obtener_precio_cuota("CFITRIPT-E", 2026, 4)
    assert "1,234.5" in out or "1234.5" in out

    conn = get_conn_for(tmp_db_path)
    row = repo_fact.get_precio(conn, "CFITRIPT-E", "2026-04-30")
    assert row["precio"] == 1234.5
    assert row["fuente"] == "LarraínVial"
    conn.close()


def test_persistencia_no_rompe_si_db_falla(tmp_db_path, monkeypatch):
    # Si la DB falla, el precio igual se devuelve (dual-write es best-effort).
    def _boom():
        raise RuntimeError("db caída")

    monkeypatch.setattr(wb, "get_conn", _boom)
    monkeypatch.setattr(wb, "_get_notation_id", lambda nemo: "1")
    monkeypatch.setattr(
        wb,
        "_fetch",
        lambda url, timeout=10: "x:[{date:new Date(2026,3,30,0,0,0),close:999.0,volume:0}]",
    )

    out = wb.obtener_precio_cuota("CFITRIPT-E", 2026, 4)
    assert "999" in out
