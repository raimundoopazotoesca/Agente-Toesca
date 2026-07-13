"""Repo de raw_eeff_line."""
import sqlite3
from tools.db.eeff_cuenta_mapper import get_canonical_code

_INSERT_COLS = [
    "fondo_key", "periodo", "cuenta_codigo", "cuenta_nombre",
    "monto_clp", "monto_uf",
    "source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id",
    "cuenta_codigo_canonical",
]


def insert_lines(
    conn: sqlite3.Connection,
    lines: list[dict],
    ingest_run_id: int,
) -> int:
    cols_sql = ", ".join(_INSERT_COLS)
    placeholders = ", ".join(["?"] * len(_INSERT_COLS))
    sql = f"INSERT OR IGNORE INTO raw_eeff_line ({cols_sql}) VALUES ({placeholders})"
    inserted = 0
    for line in lines:
        canonical = get_canonical_code(line.get("cuenta_nombre"), line.get("source_sheet"))
        values = tuple(
            ingest_run_id if c == "ingest_run_id"
            else canonical if c == "cuenta_codigo_canonical"
            else line.get(c)
            for c in _INSERT_COLS
        )
        cur = conn.execute(sql, values)
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return inserted


def mark_superseded(conn: sqlite3.Connection, file_hash: str) -> None:
    conn.execute(
        """UPDATE raw_eeff_line
              SET superseded_at = datetime('now')
            WHERE file_hash = ? AND superseded_at IS NULL""",
        (file_hash,),
    )
    conn.commit()


def list_by_periodo(
    conn: sqlite3.Connection,
    fondo_key: str,
    periodo: str,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    if include_superseded:
        sql = """SELECT * FROM raw_eeff_line
                  WHERE fondo_key=? AND periodo=?
                  ORDER BY source_row"""
    else:
        sql = """SELECT * FROM raw_eeff_line
                  WHERE fondo_key=? AND periodo=? AND superseded_at IS NULL
                  ORDER BY source_row"""
    cur = conn.execute(sql, (fondo_key, periodo))
    return cur.fetchall()
