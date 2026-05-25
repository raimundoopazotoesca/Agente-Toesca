"""Conexión SQLite y aplicación de migraciones."""
import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "memory",
    "agente_toesca.db",
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_conn_for(db_path: str) -> sqlite3.Connection:
    """Conexión a un .db específico, con foreign keys activadas."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_conn() -> sqlite3.Connection:
    """Conexión a la DB por defecto del agente."""
    return get_conn_for(DEFAULT_DB_PATH)


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def current_version(db_path: str) -> int:
    conn = get_conn_for(db_path)
    try:
        _ensure_schema_version_table(conn)
        cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        return cur.fetchone()[0]
    finally:
        conn.close()


def _discover_migrations() -> list[tuple[int, Path]]:
    """Devuelve [(version, path), …] ordenado por version."""
    out = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        name = path.stem
        version_str = name.split("_", 1)[0]
        if not version_str.isdigit():
            continue
        out.append((int(version_str), path))
    return out


def apply_migrations(db_path: str) -> list[int]:
    """Aplica todas las migraciones pendientes. Devuelve lista de versions aplicadas."""
    conn = get_conn_for(db_path)
    applied = []
    try:
        _ensure_schema_version_table(conn)
        cur = conn.execute("SELECT version FROM schema_version")
        done = {row[0] for row in cur.fetchall()}

        for version, path in _discover_migrations():
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
            conn.commit()
            applied.append(version)
    finally:
        conn.close()
    return applied
