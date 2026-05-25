"""Fixtures globales para tests."""
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """Path a un archivo SQLite temporal (no se aplica schema)."""
    return str(tmp_path / "test.db")


@pytest.fixture
def tmp_db(tmp_db_path):
    """Conexión SQLite a un archivo temporal con schema aplicado."""
    from tools.db.connection import apply_migrations, get_conn_for

    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    yield conn
    conn.close()
