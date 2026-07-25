"""Repo de dimensiones: fondos, activos, series, cuentas."""
import sqlite3

from tools.db.errors import NotFoundError


def list_fondos(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM dim_fondo ORDER BY fondo_key")
    return cur.fetchall()


def get_fondo(conn: sqlite3.Connection, fondo_key: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM dim_fondo WHERE fondo_key=?", (fondo_key,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Fondo no encontrado: {fondo_key}")
    return row


def list_activos(
    conn: sqlite3.Connection, fondo_key: str | None = None
) -> list[sqlite3.Row]:
    if fondo_key is None:
        cur = conn.execute("SELECT * FROM dim_activo ORDER BY activo_key")
    else:
        cur = conn.execute(
            "SELECT * FROM dim_activo WHERE fondo_key=? ORDER BY activo_key",
            (fondo_key,),
        )
    return cur.fetchall()


def get_activo(conn: sqlite3.Connection, activo_key: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM dim_activo WHERE activo_key=?", (activo_key,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Activo no encontrado: {activo_key}")
    return row


def list_series(
    conn: sqlite3.Connection, fondo_key: str | None = None
) -> list[sqlite3.Row]:
    if fondo_key is None:
        cur = conn.execute("SELECT * FROM dim_serie ORDER BY nemotecnico")
    else:
        cur = conn.execute(
            "SELECT * FROM dim_serie WHERE fondo_key=? ORDER BY nemotecnico",
            (fondo_key,),
        )
    return cur.fetchall()


def get_serie(conn: sqlite3.Connection, nemotecnico: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM dim_serie WHERE nemotecnico=?", (nemotecnico,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Serie no encontrada: {nemotecnico}")
    return row

# Nota: `dim_cuenta` quedó obsoleta (la reemplazó `dim_cuenta_eeff`) y nunca
# existió en producción; `upsert_cuenta`/`get_cuenta` fallaban con "no such
# table". Se eliminaron al construir el baseline.
