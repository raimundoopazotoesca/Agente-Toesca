"""Tests del dual-write de valor cuota libro (EEFF) a derived_kpi (Fase 1)."""
import tools.eeff_tools as eeff
from tools.db import repo_kpi
from tools.db.connection import apply_migrations, get_conn_for


def test_persist_valor_cuota_fondo_sin_serie(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(eeff, "get_conn", lambda: get_conn_for(tmp_db_path))

    eeff._persist_valor_cuota_libro("A&R PT", "2026-03", {None: 12345.67})

    conn = get_conn_for(tmp_db_path)
    val = repo_kpi.get(conn, "fondo", "A&R PT", "2026-03", "valor_cuota_libro", "eeff_pdf_v1")
    assert val == 12345.67
    conn.close()


def test_persist_valor_cuota_series_rentas(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(eeff, "get_conn", lambda: get_conn_for(tmp_db_path))

    eeff._persist_valor_cuota_libro(
        "A&R Rentas", "2026-03", {"A": 1000.0, "C": 2000.0, "I": 3000.0}
    )

    conn = get_conn_for(tmp_db_path)
    assert repo_kpi.get(conn, "serie", "CFITOERI1A", "2026-03", "valor_cuota_libro", "eeff_pdf_v1") == 1000.0
    assert repo_kpi.get(conn, "serie", "CFITOERI1C", "2026-03", "valor_cuota_libro", "eeff_pdf_v1") == 2000.0
    assert repo_kpi.get(conn, "serie", "CFITOERI1I", "2026-03", "valor_cuota_libro", "eeff_pdf_v1") == 3000.0
    conn.close()


def test_persist_no_rompe_si_db_falla(monkeypatch):
    def _boom():
        raise RuntimeError("db caída")

    monkeypatch.setattr(eeff, "get_conn", _boom)
    # No debe levantar excepción.
    eeff._persist_valor_cuota_libro("A&R PT", "2026-03", {None: 1.0})


def test_leer_eeff_dispara_persistencia(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(eeff, "get_conn", lambda: get_conn_for(tmp_db_path))
    monkeypatch.setattr(eeff, "buscar_pdf_eeff", lambda f, a, m: "/fake/eeff.pdf")
    monkeypatch.setattr(eeff.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(
        eeff,
        "extraer_datos_eeff",
        lambda pdf, fondo: {
            "valor_cuota": {None: 5555.0},
            "dividendos": [],
            "aportes": [],
            "texto_relevante": "",
            "error": None,
        },
    )

    eeff.leer_eeff("A&R PT", 2026, 3)

    conn = get_conn_for(tmp_db_path)
    val = repo_kpi.get(conn, "fondo", "A&R PT", "2026-03", "valor_cuota_libro", "eeff_pdf_v1")
    assert val == 5555.0
    conn.close()
