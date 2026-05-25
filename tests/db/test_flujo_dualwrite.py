"""Tests del dual-write de flujos (INMOSA) a raw_flujo_line (Fase 1)."""
import tools.noi_tools as noi
from tools.db import repo_flujo
from tools.db.connection import apply_migrations, get_conn_for


def _fake_src(tmp_path, contenido=b"contenido"):
    fake = tmp_path / "er_inmosa.xlsx"
    fake.write_bytes(contenido)
    return str(fake)


def test_persist_flujo_inmosa(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(noi, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_src(tmp_path)

    noi._persist_flujo_lines(
        "INMOSA", path, "NOI", "2026-04",
        {"Ingresos arriendo": 1000.0, "Gastos comunes": -300.0},
        tool="actualizar_noi_inmosa",
    )

    conn = get_conn_for(tmp_db_path)
    rows = repo_flujo.list_by_periodo(conn, "INMOSA", "2026-04")
    assert len(rows) == 2
    assert sorted(r["monto_clp"] for r in rows) == [-300.0, 1000.0]
    assert rows[0]["source_sheet"] == "NOI"
    conn.close()


def test_persist_flujo_idempotente(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(noi, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_src(tmp_path)
    data = {"A": 1.0, "B": 2.0}

    noi._persist_flujo_lines("INMOSA", path, "NOI", "2026-04", data, tool="t")
    noi._persist_flujo_lines("INMOSA", path, "NOI", "2026-04", data, tool="t")

    conn = get_conn_for(tmp_db_path)
    rows = repo_flujo.list_by_periodo(conn, "INMOSA", "2026-04")
    assert len(rows) == 2
    conn.close()


def test_persist_flujo_vacio_no_hace_nada(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(noi, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_src(tmp_path)

    noi._persist_flujo_lines("INMOSA", path, "NOI", "2026-04", {}, tool="t")

    conn = get_conn_for(tmp_db_path)
    rows = repo_flujo.list_by_periodo(conn, "INMOSA", "2026-04")
    assert rows == []
    conn.close()


def test_persist_flujo_no_rompe_si_db_falla(tmp_path, monkeypatch):
    def _boom():
        raise RuntimeError("db caída")

    monkeypatch.setattr(noi, "_db_get_conn", _boom)
    path = _fake_src(tmp_path)
    noi._persist_flujo_lines("INMOSA", path, "NOI", "2026-04", {"A": 1.0}, tool="t")
