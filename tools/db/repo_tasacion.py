"""Repo de tasaciones y valores de adquisición de activos."""
import sqlite3
from typing import Optional


def upsert_tasacion(
    conn: sqlite3.Connection,
    activo_key: str,
    periodo: str,
    tasador: str,
    *,
    fecha: Optional[str] = None,
    valor_uf: Optional[float] = None,
    superficie_m2: Optional[float] = None,
    uf_m2: Optional[float] = None,
    variacion_pct: Optional[float] = None,
    tasa_dcto: Optional[float] = None,
    cap_rate: Optional[float] = None,
    ltv: Optional[float] = None,
    ltc: Optional[float] = None,
    leverage_fin: Optional[float] = None,
    notas: Optional[str] = None,
    ingest_run_id: Optional[int] = None,
) -> None:
    conn.execute(
        """INSERT INTO fact_tasacion
               (activo_key, periodo, tasador, fecha, valor_uf, superficie_m2, uf_m2,
                variacion_pct, tasa_dcto, cap_rate, ltv, ltc, leverage_fin, notas, ingest_run_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(activo_key, periodo, tasador) DO UPDATE SET
             fecha          = excluded.fecha,
             valor_uf       = excluded.valor_uf,
             superficie_m2  = excluded.superficie_m2,
             uf_m2          = excluded.uf_m2,
             variacion_pct  = excluded.variacion_pct,
             tasa_dcto      = excluded.tasa_dcto,
             cap_rate       = excluded.cap_rate,
             ltv            = excluded.ltv,
             ltc            = excluded.ltc,
             leverage_fin   = excluded.leverage_fin,
             notas          = excluded.notas,
             loaded_at      = strftime('%Y-%m-%dT%H:%M:%S','now')""",
        (activo_key, periodo, tasador, fecha, valor_uf, superficie_m2, uf_m2,
         variacion_pct, tasa_dcto, cap_rate, ltv, ltc, leverage_fin, notas, ingest_run_id),
    )
    conn.commit()


def list_tasaciones(
    conn: sqlite3.Connection,
    activo_key: Optional[str] = None,
    periodo: Optional[str] = None,
) -> list[sqlite3.Row]:
    """Lista tasaciones. Sin filtros devuelve todas."""
    clauses, params = [], []
    if activo_key:
        clauses.append("activo_key = ?")
        params.append(activo_key)
    if periodo:
        clauses.append("periodo = ?")
        params.append(periodo)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.execute(
        f"SELECT * FROM fact_tasacion {where} ORDER BY activo_key, periodo, tasador",
        params,
    )
    return cur.fetchall()


def promedio_tasacion(
    conn: sqlite3.Connection,
    activo_key: str,
    periodo: str,
) -> Optional[float]:
    """Promedio de valor_uf de los tasadores de un período."""
    cur = conn.execute(
        "SELECT AVG(valor_uf) FROM fact_tasacion WHERE activo_key=? AND periodo=?",
        (activo_key, periodo),
    )
    row = cur.fetchone()
    return row[0] if row else None


def upsert_adquisicion(
    conn: sqlite3.Connection,
    activo_key: str,
    fecha_adquisicion: str,
    *,
    precio_uf: Optional[float] = None,
    valor_activo_uf: Optional[float] = None,
    superficie_m2: Optional[float] = None,
    uf_m2: Optional[float] = None,
    porcentaje_adquirido: Optional[float] = None,
    notas: Optional[str] = None,
    ingest_run_id: Optional[int] = None,
) -> None:
    conn.execute(
        """INSERT INTO fact_adquisicion
               (activo_key, fecha_adquisicion, precio_uf, valor_activo_uf,
                superficie_m2, uf_m2, porcentaje_adquirido, notas, ingest_run_id)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(activo_key) DO UPDATE SET
             fecha_adquisicion    = excluded.fecha_adquisicion,
             precio_uf            = excluded.precio_uf,
             valor_activo_uf      = excluded.valor_activo_uf,
             superficie_m2        = excluded.superficie_m2,
             uf_m2                = excluded.uf_m2,
             porcentaje_adquirido = excluded.porcentaje_adquirido,
             notas                = excluded.notas,
             loaded_at            = strftime('%Y-%m-%dT%H:%M:%S','now')""",
        (activo_key, fecha_adquisicion, precio_uf, valor_activo_uf,
         superficie_m2, uf_m2, porcentaje_adquirido, notas, ingest_run_id),
    )
    conn.commit()


def get_adquisicion(
    conn: sqlite3.Connection, activo_key: str
) -> Optional[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM fact_adquisicion WHERE activo_key=?", (activo_key,)
    )
    return cur.fetchone()


def list_adquisiciones(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM fact_adquisicion ORDER BY fecha_adquisicion"
    )
    return cur.fetchall()
