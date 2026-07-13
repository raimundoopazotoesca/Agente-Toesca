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
    # Derivar uf_dia = UF del último día calendario del mes de `fecha`
    # (convención: precio mensual usa UF de cierre de mes).
    uf_row = conn.execute(
        """SELECT valor FROM raw_uf_diaria
            WHERE fecha <= date(?, 'start of month', '+1 month', '-1 day')
            ORDER BY fecha DESC LIMIT 1""",
        (fecha,),
    ).fetchone()
    uf_dia = uf_row[0] if uf_row else None
    precio_uf = round(precio / uf_dia, 6) if uf_dia else None
    conn.execute(
        """INSERT INTO raw_valor_cuota_bursatil (nemotecnico, fecha, precio_clp, fuente, uf_dia, precio_uf)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(nemotecnico, fecha) DO UPDATE SET
             precio_clp = excluded.precio_clp,
             fuente = excluded.fuente,
             uf_dia = excluded.uf_dia,
             precio_uf = excluded.precio_uf,
             loaded_at = datetime('now')""",
        (nemotecnico, fecha, precio, fuente, uf_dia, precio_uf),
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
        """INSERT INTO raw_uf_diaria (fecha, valor, fuente)
           VALUES (?, ?, ?)
           ON CONFLICT(fecha) DO UPDATE SET
             valor = excluded.valor,
             fuente = excluded.fuente,
             loaded_at = datetime('now')""",
        (fecha, valor_clp, "repo_fact"),
    )
    conn.commit()


def get_uf(conn: sqlite3.Connection, fecha: str) -> float:
    cur = conn.execute("SELECT valor FROM fact_uf WHERE fecha=?", (fecha,))
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"UF no encontrada: {fecha}")
    return row["valor"]


def upsert_dividendo(
    conn: sqlite3.Connection,
    nemotecnico: str,
    fecha_pago: str,
    monto: float,
) -> None:
    serie = conn.execute(
        "SELECT fondo_key FROM dim_serie WHERE nemotecnico=?", (nemotecnico,)
    ).fetchone()
    if serie is None:
        raise NotFoundError(f"Serie no encontrada: {nemotecnico}")

    uf_row = conn.execute(
        "SELECT valor FROM raw_uf_diaria WHERE fecha<=? ORDER BY fecha DESC LIMIT 1",
        (fecha_pago,),
    ).fetchone()
    monto_uf = monto / uf_row[0] if uf_row and uf_row[0] else None
    existing = conn.execute(
        """SELECT id FROM raw_dividendo
           WHERE nemotecnico=? AND fecha_pago=? AND tipo='dividendo'
             AND superseded_at IS NULL
           ORDER BY id DESC LIMIT 1""",
        (nemotecnico, fecha_pago),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE raw_dividendo
               SET monto_clp_cuota=?, monto_uf_cuota=?, loaded_at=datetime('now')
               WHERE id=?""",
            (monto, monto_uf, existing[0]),
        )
    else:
        conn.execute(
            """INSERT INTO raw_dividendo
               (fondo_key, nemotecnico, fecha_pago, monto_clp_cuota,
                monto_uf_cuota, periodo, tipo, source_file, file_hash)
               VALUES (?, ?, ?, ?, ?, substr(?, 1, 7), 'dividendo',
                       'repo_fact', ?)""",
            (
                serie[0], nemotecnico, fecha_pago, monto, monto_uf, fecha_pago,
                f"repo_fact:{nemotecnico}:{fecha_pago}",
            ),
        )
    conn.commit()


def list_dividendos(conn: sqlite3.Connection, nemotecnico: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM fact_dividendo WHERE nemotecnico=? ORDER BY fecha_pago",
        (nemotecnico,),
    )
    return cur.fetchall()
