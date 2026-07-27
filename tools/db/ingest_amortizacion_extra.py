"""Registro de pagos extraordinarios (prepago/bullet) sobre créditos vigentes.

No reemplaza raw_amortizacion (cronograma completo, recargado en bloque desde
el Excel maestro por tools/db/ingest_financing.py) — es un log de eventos
independiente. Al registrar un evento se ajusta hacia adelante raw_saldo_deuda
(solo períodos con is_proyeccion=1) para que los KPIs de deuda/LTV reflejen el
prepago sin esperar el próximo reload completo del Excel.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / "memory" / "agente_toesca_v2.db"


def listar_creditos(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT credito_key, acreedor, activo_key, fondo_key "
        "FROM dim_credito WHERE estado='VIGENTE' ORDER BY fondo_key, activo_key"
    ).fetchall()
    return [
        {
            "credito_key": r["credito_key"],
            "acreedor": r["acreedor"],
            "activo_key": r["activo_key"],
            "fondo_key": r["fondo_key"],
        }
        for r in rows
    ]


def historial(con: sqlite3.Connection, credito_key: str) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT fecha, monto_uf, nota FROM raw_amortizacion_extraordinaria "
        "WHERE credito_key=? AND superseded_at IS NULL ORDER BY fecha DESC",
        (credito_key,),
    ).fetchall()
    return [{"fecha": r["fecha"], "monto_uf": r["monto_uf"], "nota": r["nota"]} for r in rows]


def commit(
    con: sqlite3.Connection,
    credito_key: str,
    fecha: str,
    monto_uf: float,
    nota: str | None = None,
) -> dict[str, Any]:
    row = con.execute(
        "SELECT estado FROM dim_credito WHERE credito_key=?", (credito_key,)
    ).fetchone()
    if row is None:
        raise ValueError(f"El crédito '{credito_key}' no existe.")
    if row["estado"] != "VIGENTE":
        raise ValueError(
            f"El crédito '{credito_key}' no está VIGENTE (estado={row['estado']}); "
            "no puede recibir un pago extraordinario."
        )
    if monto_uf is None or not isinstance(monto_uf, (int, float)) or monto_uf <= 0:
        raise ValueError("El monto (monto_uf) debe ser un número mayor a 0.")
    try:
        fecha_parsed = date.fromisoformat(fecha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Fecha inválida: {fecha!r}. Usa formato YYYY-MM-DD.") from exc

    periodo = fecha_parsed.strftime("%Y-%m")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = con.cursor()
    cur.execute(
        "INSERT INTO ingest_run (tool, started_at, status, periodo_declarado) VALUES (?,?,?,?)",
        ("ingest_amortizacion_extra", now, "running", periodo),
    )
    run_id = cur.lastrowid
    try:
        cur.execute(
            """INSERT INTO raw_amortizacion_extraordinaria
               (credito_key, fecha, periodo, monto_uf, nota, ingest_run_id, loaded_at)
               VALUES (?,?,?,?,?,?,?)""",
            (credito_key, fecha, periodo, monto_uf, nota, run_id, now),
        )
        cur.execute(
            "UPDATE raw_saldo_deuda SET saldo_uf = saldo_uf - ? "
            "WHERE credito_key=? AND periodo>=? AND is_proyeccion=1",
            (monto_uf, credito_key, periodo),
        )
        periodos_ajustados = cur.rowcount
        cur.execute(
            "UPDATE ingest_run SET ended_at=?, status='ok', rows_loaded=1 WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), run_id),
        )
        con.commit()
    except Exception:
        con.rollback()
        cur.execute(
            "UPDATE ingest_run SET ended_at=?, status='error' WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), run_id),
        )
        con.commit()
        raise

    return {
        "status": "ok",
        "credito_key": credito_key,
        "periodo": periodo,
        "monto_uf": monto_uf,
        "periodos_ajustados": periodos_ajustados,
    }
