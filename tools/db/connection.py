"""Conexión SQLite y aplicación de migraciones."""
import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "memory",
    "agente_toesca_v2.db",
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_conn_for(db_path: str) -> sqlite3.Connection:
    """Conexión a un .db específico, con foreign keys activadas."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
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
    versions = [version for version, _ in out]
    duplicates = sorted({version for version in versions if versions.count(version) > 1})
    if duplicates:
        raise RuntimeError(f"Versiones de migración duplicadas: {duplicates}")
    return out


def _execute_migration(conn: sqlite3.Connection, sql: str) -> None:
    """Ejecuta sentencias SQL sin hacer commits implícitos.

    ``executescript`` confirma cualquier transacción pendiente antes de ejecutar,
    lo que podía dejar una migración aplicada a medias pero sin registrar su
    versión. ``complete_statement`` permite conservar una sola transacción para
    el DDL, los datos y ``schema_version``.
    """
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if not sqlite3.complete_statement(statement):
            continue
        if statement.strip().strip(";"):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                # Compatibilidad con DBs antiguas donde un ADD COLUMN fue
                # aplicado manualmente pero la versión no quedó registrada.
                if "duplicate column name" not in str(exc).lower():
                    raise
        statement = ""
    remaining = "\n".join(
        line for line in statement.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ).strip()
    if remaining:
        raise sqlite3.OperationalError("Migración contiene una sentencia SQL incompleta")


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
            try:
                conn.execute("BEGIN IMMEDIATE")
                _execute_migration(conn, sql)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version,)
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise RuntimeError(
                    f"Falló migración {version:03d} ({path.name}): {exc}"
                ) from exc
            applied.append(version)
    finally:
        conn.close()
    return applied
