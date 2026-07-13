"""Repo de derived_kpi — KPIs calculados, en formato largo para dashboards."""
import sqlite3

from tools.db.errors import NotFoundError


def upsert(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
    kpi: str,
    valor: float,
    unidad: str | None,
    formula: str,
    ingest_run_id: int | None = None,
    variante: str | None = None,
) -> None:
    if variante is None:
        existing = conn.execute(
            """SELECT id FROM derived_kpi
               WHERE entidad_tipo=? AND entidad_key=? AND periodo=? AND kpi=?
                 AND variante IS NULL
               ORDER BY id DESC LIMIT 1""",
            (entidad_tipo, entidad_key, periodo, kpi),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE derived_kpi
                   SET valor=?, unidad=?, formula=?, ingest_run_id=?,
                       computed_at=datetime('now')
                   WHERE id=?""",
                (valor, unidad, formula, ingest_run_id, existing[0]),
            )
            conn.commit()
            return

    conn.execute(
        """INSERT INTO derived_kpi
             (entidad_tipo, entidad_key, periodo, kpi, variante, valor, unidad, formula, ingest_run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(entidad_tipo, entidad_key, periodo, kpi, variante) DO UPDATE SET
             valor         = excluded.valor,
             unidad        = excluded.unidad,
             formula        = excluded.formula,
             ingest_run_id = excluded.ingest_run_id,
             computed_at   = datetime('now')""",
        (entidad_tipo, entidad_key, periodo, kpi, variante, valor, unidad, formula, ingest_run_id),
    )
    conn.commit()


def get(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
    kpi: str,
    formula: str | None = None,
    variante: str | None = None,
) -> float:
    sql = """SELECT valor FROM derived_kpi
              WHERE entidad_tipo=? AND entidad_key=? AND periodo=? AND kpi=?
                AND variante IS ?"""
    params: list = [entidad_tipo, entidad_key, periodo, kpi, variante]
    if formula is not None:
        sql += " AND formula = ?"
        params.append(formula)
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        raise NotFoundError(
            f"KPI no encontrado: {entidad_tipo}/{entidad_key} {periodo} {kpi} variante={variante}"
        )
    return row["valor"]


def serie_temporal(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    kpi: str,
    desde: str | None = None,
    hasta: str | None = None,
    formula: str | None = None,
    variante: str | None = None,
) -> list[sqlite3.Row]:
    sql = """SELECT periodo, valor, unidad, formula, variante
               FROM derived_kpi
              WHERE entidad_tipo=? AND entidad_key=? AND kpi=?
                AND variante IS ?"""
    params: list = [entidad_tipo, entidad_key, kpi, variante]
    if desde is not None:
        sql += " AND periodo >= ?"
        params.append(desde)
    if hasta is not None:
        sql += " AND periodo <= ?"
        params.append(hasta)
    if formula is not None:
        sql += " AND formula = ?"
        params.append(formula)
    sql += " ORDER BY periodo"
    cur = conn.execute(sql, params)
    return cur.fetchall()


def snapshot_periodo(
    conn: sqlite3.Connection,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
) -> list[sqlite3.Row]:
    cur = conn.execute(
        """SELECT kpi, variante, valor, unidad, formula
             FROM derived_kpi
            WHERE entidad_tipo=? AND entidad_key=? AND periodo=?
            ORDER BY kpi, variante""",
        (entidad_tipo, entidad_key, periodo),
    )
    return cur.fetchall()
