"""Tests de los seeds de dimensiones."""
from tools.db.connection import apply_migrations, get_conn_for


def test_seed_fondos(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT fondo_key FROM dim_fondo ORDER BY fondo_key")
    keys = [row[0] for row in cur.fetchall()]
    assert keys == ["A&R Apoquindo", "A&R PT", "A&R Rentas"]


def test_seed_activos(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT activo_key, fondo_key FROM dim_activo ORDER BY activo_key")
    rows = cur.fetchall()
    keys = [r[0] for r in rows]
    assert set(keys) == {"INMOSA", "PT", "Viña Centro", "Mall Curicó", "Apoquindo", "Apo3001"}


def test_seed_series(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT nemotecnico, fondo_key, serie FROM dim_serie ORDER BY nemotecnico")
    rows = [tuple(r) for r in cur.fetchall()]
    assert ("CFITRIPT-E", "A&R PT", "Única") in rows
    assert ("CFITOERI1A", "A&R Rentas", "A") in rows
    assert ("CFITOERI1C", "A&R Rentas", "C") in rows
    assert ("CFITOERI1I", "A&R Rentas", "I") in rows


def test_seed_idempotent(tmp_db_path):
    apply_migrations(tmp_db_path)
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT COUNT(*) FROM dim_fondo")
    assert cur.fetchone()[0] == 3
