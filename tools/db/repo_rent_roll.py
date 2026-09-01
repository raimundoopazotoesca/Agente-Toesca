"""Repo de raw_rent_roll_line."""
import sqlite3

_INSERT_COLS = [
    "activo_key", "periodo", "unidad", "arrendatario", "m2", "renta_uf",
    "vencimiento", "extra_json", "source_file", "source_sheet", "source_row",
    "file_hash", "ingest_run_id",
]


def insert_lines(
    conn: sqlite3.Connection,
    lines: list[dict],
    ingest_run_id: int,
) -> int:
    """Inserta líneas. Devuelve cuántas se insertaron (omite duplicados por (file_hash, source_row))."""
    cols_sql = ", ".join(_INSERT_COLS)
    placeholders = ", ".join(["?"] * len(_INSERT_COLS))
    sql = f"INSERT OR IGNORE INTO raw_rent_roll_line ({cols_sql}) VALUES ({placeholders})"

    inserted = 0
    for line in lines:
        values = tuple(
            ingest_run_id if c == "ingest_run_id" else line.get(c)
            for c in _INSERT_COLS
        )
        cur = conn.execute(sql, values)
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return inserted


def mark_superseded(conn: sqlite3.Connection, file_hash: str) -> None:
    conn.execute(
        """UPDATE raw_rent_roll_line
              SET superseded_at = datetime('now')
            WHERE file_hash = ? AND superseded_at IS NULL""",
        (file_hash,),
    )
    conn.commit()


# ── pipeline v2 ─────────────────────────────────────────────────────────────
# El camino nuevo (tools/db/ingest_jll_planilla.py) escribe columnas que el
# legacy no conoce y exige procedencia. Va aparte para no tocar `insert_lines`,
# de la que dependen el dual-write y la ingesta clásica.

_INSERT_COLS_V2 = _INSERT_COLS + [
    "renta_uf_m2", "fecha_corte_fuente", "renta_semantica",
    "fuente_proveedor", "fuente_formato",
]


def insert_lines_v2(
    conn: sqlite3.Connection,
    lines: list[dict],
    *,
    ingest_run_id: int,
    fuente_proveedor: str,
    fuente_formato: str,
) -> int:
    """Inserta líneas del pipeline v2. No hace commit: la transacción es del caller.

    `fuente_proveedor` y `fuente_formato` son obligatorios para filas nuevas. No
    se imponen como NOT NULL de tabla porque el histórico legítimamente los
    tiene en NULL (su procedencia no siempre es derivable).
    """
    if not fuente_proveedor or not fuente_formato:
        raise ValueError(
            "fuente_proveedor y fuente_formato son obligatorios en el pipeline v2"
        )
    cols_sql = ", ".join(_INSERT_COLS_V2)
    placeholders = ", ".join(["?"] * len(_INSERT_COLS_V2))
    # INSERT normal, no "OR IGNORE": en el pipeline v2 una violación de
    # restricción debe abortar la transacción, no perder la fila en silencio.
    # `insert_lines` (legacy) conserva su comportamiento.
    sql = (
        f"INSERT INTO raw_rent_roll_line ({cols_sql}) "
        f"VALUES ({placeholders})"
    )
    fijos = {
        "ingest_run_id": ingest_run_id,
        "fuente_proveedor": fuente_proveedor,
        "fuente_formato": fuente_formato,
    }
    inserted = 0
    for line in lines:
        values = tuple(fijos.get(c, line.get(c)) for c in _INSERT_COLS_V2)
        cur = conn.execute(sql, values)
        inserted += max(cur.rowcount, 0)
    return inserted


def mark_superseded_scope(conn: sqlite3.Connection, scope: set) -> int:
    """Supersede lo vivo de cada (fuente_proveedor, activo_key, periodo).

    El proveedor entra en la clave para que una fuente no borre los datos de
    otra sobre el mismo activo y período. Filas con `fuente_proveedor` NULL
    (histórico sin procedencia declarada) NO son alcanzadas por este barrido:
    convertirlas exige un paso explícito, no un efecto lateral de ingestar.
    """
    afectadas = 0
    for proveedor, activo, periodo in sorted(scope):
        cur = conn.execute(
            """UPDATE raw_rent_roll_line
                  SET superseded_at = datetime('now')
                WHERE fuente_proveedor = ? AND activo_key = ? AND periodo = ?
                  AND superseded_at IS NULL""",
            (proveedor, activo, periodo),
        )
        afectadas += max(cur.rowcount, 0)
    return afectadas


def semanticas_vivas(conn: sqlite3.Connection, activo_key: str, periodo: str) -> set:
    """Valores de `renta_semantica` presentes en las filas vivas de un período.

    Sostiene el invariante de semántica no mixta: ningún (activo, periodo) puede
    tener filas vivas con más de una semántica de renta.
    """
    rows = conn.execute(
        """SELECT DISTINCT renta_semantica FROM raw_rent_roll_line
            WHERE activo_key = ? AND periodo = ? AND superseded_at IS NULL""",
        (activo_key, periodo),
    ).fetchall()
    return {r[0] for r in rows}


def list_by_periodo(
    conn: sqlite3.Connection,
    activo_key: str,
    periodo: str,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    if include_superseded:
        sql = """SELECT * FROM raw_rent_roll_line
                  WHERE activo_key=? AND periodo=?
                  ORDER BY source_row"""
    else:
        sql = """SELECT * FROM raw_rent_roll_line
                  WHERE activo_key=? AND periodo=? AND superseded_at IS NULL
                  ORDER BY source_row"""
    cur = conn.execute(sql, (activo_key, periodo))
    return cur.fetchall()
