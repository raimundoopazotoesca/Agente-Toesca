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
    # Catálogo real de activos (el que tiene producción). Ojo: 'PT' y 'Apoquindo'
    # NO son activo_key — son el fondo y el agregado de sus dos edificios. Los
    # activos de PT son Torre A, Boulevard y Parking PT; los de Apo, Apo4501 y
    # Apo4700. Los seeds antiguos sí los traían y por eso este test los exigía.
    # PROVEEDOR_ACTIVOS['jll'] todavía los espera: ver ROADMAP §8 (pendiente).
    assert {"INMOSA", "Viña Centro", "Mall Curicó", "Apo3001", "Sucden",
            "Torre A", "Boulevard", "Apo4501", "Apo4700"} <= set(keys)
    assert "PT" not in keys and "Apoquindo" not in keys


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
