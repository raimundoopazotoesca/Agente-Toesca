"""Tests de los seeds de dimensiones."""
from tools.db.connection import apply_migrations, get_conn_for


def test_seed_fondos(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT fondo_key FROM dim_fondo ORDER BY fondo_key")
    keys = [row[0] for row in cur.fetchall()]
    assert keys == ["Apo", "PT", "TRI"]


def test_seed_activos(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT activo_key, fondo_key FROM dim_activo ORDER BY activo_key")
    rows = cur.fetchall()
    keys = [r[0] for r in rows]
    # Sucden se agrega en la migración 007 (activo del NOI).
    assert set(keys) == {"INMOSA", "PT", "Viña Centro", "Mall Curicó", "Apoquindo", "Apo3001", "Sucden"}


def test_seed_series(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT nemotecnico, fondo_key, serie FROM dim_serie ORDER BY nemotecnico")
    rows = [tuple(r) for r in cur.fetchall()]
    assert ("CFITRIPT-E", "PT", "Única") in rows
    assert ("CFITOERI1A", "TRI", "A") in rows
    assert ("CFITOERI1C", "TRI", "C") in rows
    assert ("CFITOERI1I", "TRI", "I") in rows


def test_seed_idempotent(tmp_db_path):
    apply_migrations(tmp_db_path)
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT COUNT(*) FROM dim_fondo")
    assert cur.fetchone()[0] == 3
