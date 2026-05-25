"""Repo de hechos: precios de cuota, UF, dividendos."""
import sqlite3

from tools.db.errors import NotFoundError


def upsert_precio(
    conn: sqlite3.Connection,
    nemotecnico: str,
    fecha: str,
    precio: float,
    fuente: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO fact_precio_cuota (nemotecnico, fecha, precio, fuente)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(nemotecnico, fecha) DO UPDATE SET
             precio = excluded.precio,
             fuente = excluded.fuente,
             loaded_at = datetime('now')""",
        (nemotecnico, fecha, precio, fuente),
    )
    conn.commit()


def get_precio(conn: sqlite3.Connection, nemotecnico: str, fecha: str) -> sqlite3.Row:
    cur = conn.execute(
        "SELECT * FROM fact_precio_cuota WHERE nemotecnico=? AND fecha=?",
        (nemotecnico, fecha),
    )
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Precio no encontrado: {nemotecnico} {fecha}")
    return row


def upsert_uf(conn: sqlite3.Connection, fecha: str, valor_clp: float) -> None:
    conn.execute(
        """INSERT INTO fact_uf (fecha, valor_clp)
           VALUES (?, ?)
           ON CONFLICT(fecha) DO UPDATE SET
             valor_clp = excluded.valor_clp,
             loaded_at = datetime('now')""",
        (fecha, valor_clp),
    )
    conn.commit()


def get_uf(conn: sqlite3.Connection, fecha: str) -> float:
    cur = conn.execute("SELECT valor_clp FROM fact_uf WHERE fecha=?", (fecha,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"UF no encontrada: {fecha}")
    return row["valor_clp"]


def upsert_dividendo(
    conn: sqlite3.Connection,
    nemotecnico: str,
    fecha_pago: str,
    monto: float,
) -> None:
    conn.execute(
        """INSERT INTO fact_dividendo (nemotecnico, fecha_pago, monto)
           VALUES (?, ?, ?)
           ON CONFLICT(nemotecnico, fecha_pago) DO UPDATE SET
             monto = excluded.monto,
             loaded_at = datetime('now')""",
        (nemotecnico, fecha_pago, monto),
    )
    conn.commit()


def list_dividendos(conn: sqlite3.Connection, nemotecnico: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM fact_dividendo WHERE nemotecnico=? ORDER BY fecha_pago",
        (nemotecnico,),
    )
    return cur.fetchall()
