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


def _execute_migration(conn: sqlite3.Connection, sql: str) -> None:
    """Ejecuta un archivo de migración.

    Usa executescript para SQL multi-statement. Si falla con 'duplicate column
    name', intenta ejecutar las líneas de ALTER TABLE individualmente, tolerando
    las que ya se aplicaron.
    """
    try:
        conn.executescript(sql)
        return
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise

    # Segunda pasada: extraer ALTER TABLE ... ADD COLUMN y ejecutarlos con tolerancia
    import re
    lines = sql.splitlines()
    alter_stmts = []
    in_alter = False
    buf = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"ALTER\s+TABLE\b", stripped, re.IGNORECASE):
            in_alter = True
            buf = [line]
        elif in_alter:
            buf.append(line)
            if stripped.endswith(";"):
                alter_stmts.append(" ".join(buf))
                in_alter = False
                buf = []
        if not in_alter and stripped.endswith(";") and buf:
            in_alter = False
            buf = []

    # Reemplazar cada ALTER TABLE en el SQL por un marcador y ejecutar sin ellos
    sql_no_alter = re.sub(
        r"ALTER\s+TABLE\b[^;]+;",
        "",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    conn.executescript(sql_no_alter)

    # Ejecutar los ALTER TABLE tolerando duplicados
    for stmt in alter_stmts:
        try:
            conn.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError as ex:
            if "duplicate column name" not in str(ex).lower():
                raise


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
            _execute_migration(conn, sql)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
            conn.commit()
            applied.append(version)
    finally:
        conn.close()
    return applied
