"""Tests del sistema de migraciones."""
import sqlite3

import pytest

from tools.db.connection import apply_migrations, get_conn_for, current_version
from tools.db import connection


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
    assert {"dim_fondo", "dim_activo", "dim_serie", "dim_cuenta_eeff"} <= tables


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


def test_apply_migrations_creates_fact_compat_views(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='view'")
    views = {row[0] for row in cur.fetchall()}
    assert {"fact_precio_cuota", "fact_uf", "fact_dividendo"} <= views


def test_apply_migrations_creates_derived_and_audit_tables(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert {"derived_kpi", "ingest_run"} <= tables


@pytest.mark.xfail(
    reason="Producción no tiene UNIQUE(file_hash, source_row): el INSERT OR IGNORE "
           "de los repos es un no-op y por eso hay duplicados vivos. La restricción "
           "entra tras el saneamiento (ROADMAP F0.4); cuando eso ocurra este test "
           "pasará y strict=True obligará a quitar el marcador.",
    strict=True,
)
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


def test_failed_migration_rolls_back_schema_and_version(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "061_broken.sql").write_text(
        "CREATE TABLE should_rollback(id INTEGER);\nINVALID SQL;\n",
        encoding="utf-8",
    )
    db_path = str(tmp_path / "broken.db")
    monkeypatch.setattr(connection, "MIGRATIONS_DIR", migrations)

    with pytest.raises(RuntimeError, match="061_broken.sql"):
        apply_migrations(db_path)

    conn = get_conn_for(db_path)
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='should_rollback'"
    ).fetchone() is None
    # El baseline sí se aplicó (crea el esquema); la migración rota se revierte.
    assert current_version(db_path) == connection.BASELINE_VERSION
