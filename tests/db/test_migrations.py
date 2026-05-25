"""Tests del sistema de migraciones."""
import sqlite3

import pytest

from tools.db.connection import apply_migrations, get_conn_for, current_version


def test_apply_migrations_creates_schema_version_table(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    assert cur.fetchone() is not None


def test_apply_migrations_records_versions(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT version FROM schema_version ORDER BY version")
    versions = [row[0] for row in cur.fetchall()]
    assert versions == sorted(versions)
    assert 1 in versions


def test_apply_migrations_is_idempotent(tmp_db_path):
    apply_migrations(tmp_db_path)
    v1 = current_version(tmp_db_path)
    apply_migrations(tmp_db_path)
    v2 = current_version(tmp_db_path)
    assert v1 == v2


def test_apply_migrations_creates_dim_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cur.fetchall()}
    assert {"dim_fondo", "dim_activo", "dim_serie", "dim_cuenta"} <= tables


def test_apply_migrations_creates_raw_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert {
        "raw_rent_roll_line",
        "raw_eeff_line",
        "raw_flujo_line",
        "raw_er_activo_line",
    } <= tables


def test_apply_migrations_creates_fact_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert {"fact_precio_cuota", "fact_uf", "fact_dividendo"} <= tables


def test_apply_migrations_creates_derived_and_audit_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert {"derived_kpi", "ingest_run", "publish_run"} <= tables


def test_raw_rent_roll_unique_file_hash_source_row(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    conn.execute("INSERT INTO dim_fondo(fondo_key, nombre) VALUES ('F1', 'F1')")
    conn.execute(
        "INSERT INTO dim_activo(activo_key, fondo_key, nombre) VALUES ('A1','F1','A1')"
    )
    conn.execute(
        """INSERT INTO raw_rent_roll_line(activo_key, periodo, file_hash, source_row)
           VALUES ('A1','2026-04','HASH1', 5)"""
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO raw_rent_roll_line(activo_key, periodo, file_hash, source_row)
               VALUES ('A1','2026-04','HASH1', 5)"""
        )
        conn.commit()
