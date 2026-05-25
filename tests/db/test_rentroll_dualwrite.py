"""Tests del dual-write de rent roll a raw_rent_roll_line (Fase 1)."""
import tools.rentroll_tools as rr
from tools.db import repo_rent_roll
from tools.db.connection import apply_migrations, get_conn_for


def _fake_src(tmp_path):
    fake = tmp_path / "rr.xlsx"
    fake.write_bytes(b"contenido rr")
    return str(fake)


def _source(activo1, n=2):
    return {
        (f"Edificio{i}", f"Local {i}"): {
            "Activo1": activo1,
            "Arrendatario": f"Tenant {i}",
            "Area Arrendable (m2)": 100.0 + i,
            "Renta Fija (UF/m2 /mes)": 0.5,
            "Término del Contrato": "2027-12-31",
            "Tipo Activo 1": "Oficina",
        }
        for i in range(n)
    }


def test_persist_rent_roll_jll_pt(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(rr, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_src(tmp_path)

    n = rr._persist_rent_roll(path, "2026-03", _source("Fondo Rentas PT", 3), "jll")
    assert n == 3

    conn = get_conn_for(tmp_db_path)
    rows = repo_rent_roll.list_by_periodo(conn, "PT", "2026-03")
    assert len(rows) == 3
    assert rows[0]["arrendatario"] == "Tenant 0"
    assert rows[0]["renta_uf"] == 0.5
    conn.close()


def test_persist_rent_roll_mapea_todos_los_activos(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(rr, "_db_get_conn", lambda: get_conn_for(tmp_db_path))

    casos = {
        "Fondo Rentas Apoquindo": "Apoquindo",
        "Apoquindo 3001": "Apo3001",
        "Paseo Viña Centro": "Viña Centro",
        "Mall Curicó": "Mall Curicó",
    }
    for activo1, activo_key in casos.items():
        path = tmp_path / f"{activo_key}.xlsx"
        path.write_bytes(f"contenido {activo_key}".encode())
        rr._persist_rent_roll(str(path), "2026-03", _source(activo1, 1), "p")
        conn = get_conn_for(tmp_db_path)
        rows = repo_rent_roll.list_by_periodo(conn, activo_key, "2026-03")
        assert len(rows) == 1, f"fallo para {activo_key}"
        conn.close()


def test_persist_rent_roll_salta_activo_no_mapeable(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(rr, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_src(tmp_path)

    n = rr._persist_rent_roll(path, "2026-03", _source("Activo Desconocido", 2), "jll")
    assert n == 0


def test_persist_rent_roll_idempotente(tmp_db_path, tmp_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(rr, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = _fake_src(tmp_path)
    data = _source("Fondo Rentas PT", 2)

    assert rr._persist_rent_roll(path, "2026-03", data, "jll") == 2
    assert rr._persist_rent_roll(path, "2026-03", data, "jll") == 0


def test_persist_rent_roll_no_rompe_si_db_falla(tmp_path, monkeypatch):
    def _boom():
        raise RuntimeError("db caída")

    monkeypatch.setattr(rr, "_db_get_conn", _boom)
    path = _fake_src(tmp_path)
    assert rr._persist_rent_roll(path, "2026-03", _source("Fondo Rentas PT", 1), "jll") == 0


def test_persist_rent_roll_real_jll_si_existe(tmp_db_path, monkeypatch):
    """Si hay un RR JLL real sincronizado, verifica el mapeo extremo a extremo."""
    import os
    from tools.sharepoint_paths import RR_JLL_DIR

    candidatos = []
    for base in (RR_JLL_DIR,):
        for y in ("2025", "2026"):
            d = os.path.join(base, y)
            if os.path.isdir(d):
                candidatos += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".xlsx")]
    if not candidatos:
        import pytest
        pytest.skip("No hay RR JLL real sincronizado")

    apply_migrations(tmp_db_path)
    monkeypatch.setattr(rr, "_db_get_conn", lambda: get_conn_for(tmp_db_path))
    path = sorted(candidatos)[-1]
    data = rr._read_source_data(path)
    n = rr._persist_rent_roll(path, "2026-03", data, "jll")
    assert n > 0

    conn = get_conn_for(tmp_db_path)
    total = conn.execute("SELECT COUNT(*) FROM raw_rent_roll_line").fetchone()[0]
    activos = [r[0] for r in conn.execute("SELECT DISTINCT activo_key FROM raw_rent_roll_line")]
    conn.close()
    assert total == n
    assert all(a in {"PT", "Apoquindo", "Apo3001"} for a in activos)
