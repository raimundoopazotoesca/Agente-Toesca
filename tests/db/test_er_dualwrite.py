"""Tests del dual-write de ER Viña/Curicó a raw_er_activo_line (Fase 1)."""
import tools.noi_tools as noi
from tools.db import repo_er_activo
from tools.db.connection import apply_migrations, get_conn_for


def _fake_eeff(tmp_path, contenido=b"contenido"):
    fake = tmp_path / "eeff.xlsx"
    fake.write_bytes(contenido)
    return str(fake)


def test_persist_er_lines_vina(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(noi, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_eeff(tmp_path)

    noi._persist_er_lines("vina", path, "2026-03", {"4-01 Arriendos": 1000.0, "5-01 Gastos": -500.0})

    conn = get_conn_for(tmp_db_path)
    rows = repo_er_activo.list_by_periodo(conn, "Viña Centro", "2026-03")
    assert len(rows) == 2
    assert sorted(r["monto_clp"] for r in rows) == [-500.0, 1000.0]
    conn.close()


def test_persist_er_lines_curico(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(noi, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_eeff(tmp_path)

    noi._persist_er_lines("curico", path, "2026-03", {"4-01": 777.0})

    conn = get_conn_for(tmp_db_path)
    rows = repo_er_activo.list_by_periodo(conn, "Mall Curicó", "2026-03")
    assert len(rows) == 1
    assert rows[0]["cuenta_nombre"] == "4-01"
    conn.close()


def test_persist_er_idempotente(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(noi, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_eeff(tmp_path)
    valores = {"4-01": 1.0, "5-01": 2.0}

    noi._persist_er_lines("vina", path, "2026-03", valores)
    noi._persist_er_lines("vina", path, "2026-03", valores)  # mismo archivo → no duplica

    conn = get_conn_for(tmp_db_path)
    rows = repo_er_activo.list_by_periodo(conn, "Viña Centro", "2026-03")
    assert len(rows) == 2
    conn.close()


def test_persist_er_registra_ingest_run(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(noi, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_eeff(tmp_path)

    noi._persist_er_lines("vina", path, "2026-03", {"4-01": 1.0})

    conn = get_conn_for(tmp_db_path)
    run = conn.execute(
        "SELECT tool, status, rows_loaded FROM ingest_run ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert run["tool"] == "actualizar_er_vina"
    assert run["status"] == "ok"
    assert run["rows_loaded"] == 1
    conn.close()


def test_persist_er_no_rompe_si_db_falla(tmp_path, monkeypatch):
    def _boom():
        raise RuntimeError("db caída")

    monkeypatch.setattr(noi, "_db_get_conn", _boom)
    path = _fake_eeff(tmp_path)
    # No debe levantar excepción.
    noi._persist_er_lines("vina", path, "2026-03", {"4-01": 1.0})
