"""Ingesta de Sucden por confirmación (sin archivo) — contrato fijo.

Sucden es un contrato de arriendo fijo (confirmado por el usuario 2026-07-27):
no hay planilla mensual que leer, los montos no cambian mes a mes. En vez del
flujo de subir un xlsx (como INMOSA/Viña/Curicó), el usuario ve los 4 montos
vigentes precargados en inputs editables y confirma el período.

Los valores vigentes ("default") se guardan en `sucden_valores_fijos`
(migración 071), sembrada con los montos confirmados por el usuario:
  - Ingresos por Arriendos:  2248.4709 UF
  - Contribuciones:          -38969106/3 CLP / UF fija (39841.72, UF de
                              cierre marzo-2026, fecha en que el contrato se
                              fijó) = -326.03266124052874 UF
  - Sobretasa:               -140 UF
  - Seguros:                 0 UF

Si el usuario edita un monto en la UI puede elegir:
  - "solo este período": el override se usa una vez, `sucden_valores_fijos`
    no se toca.
  - "permanente": se actualiza `sucden_valores_fijos` (aplica desde el
    próximo período que se ingeste) y también se usa para el período actual.

Solo permite ingestar períodos que AÚN NO existen en la DB para Sucden —
por diseño, este flujo es solo hacia adelante; el histórico ya ingestado
(vía ingest_er_sucden.py, planilla real) no se toca.
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Optional

_ACTIVO_KEY = "Sucden"

_NOMBRES: dict[str, str] = {
    "SUCDEN_ING_ARR":   "Ingresos por Arriendos",
    "SUCDEN_CONTRIB":   "Contribuciones",
    "SUCDEN_SOBRETASA": "Sobretasa",
    "SUCDEN_SEG":       "Seguros",
}
_SECCIONES: dict[str, str] = {
    "SUCDEN_ING_ARR":   "INGRESOS_OPERACION",
    "SUCDEN_CONTRIB":   "GASTOS_OPERACION",
    "SUCDEN_SOBRETASA": "GASTOS_OPERACION",
    "SUCDEN_SEG":       "GASTOS_OPERACION",
}


def _ultimo_periodo(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(periodo) FROM raw_er_activo_line WHERE activo_key=? AND superseded_at IS NULL",
        (_ACTIVO_KEY,),
    ).fetchone()
    return row[0] if row else None


def valores_vigentes(conn: "sqlite3.Connection | None" = None) -> dict[str, float]:
    """Montos vigentes ('default') por cuenta_codigo, desde sucden_valores_fijos."""
    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()
    try:
        rows = conn.execute("SELECT cuenta_codigo, monto_uf FROM sucden_valores_fijos").fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        if owns_conn:
            conn.close()


def generar_lineas(periodo: str, valores: dict[str, float]) -> list[dict]:
    return [
        {
            "activo_key":     _ACTIVO_KEY,
            "periodo":        periodo,
            "cuenta_codigo":  codigo,
            "cuenta_nombre":  _NOMBRES[codigo],
            "monto_clp":      monto,
            "monto_uf":       None,
            "seccion":        _SECCIONES[codigo],
            "es_operacional": 1,
            "source_file":    "fijo:Sucden (contrato fijo, sin planilla)",
            "source_sheet":   None,
            "source_row":     None,
        }
        for codigo, monto in valores.items()
    ]


def validate_periodo(periodo: str, overrides: "dict[str, float] | None" = None,
                      conn: "sqlite3.Connection | None" = None) -> dict:
    """Valida que el período no exista aún en la DB (hacia adelante, sin
    tocar histórico) y devuelve el resumen de los montos a ingestar (los
    vigentes en `sucden_valores_fijos`, salvo los que traiga `overrides`)."""
    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()
    try:
        existente = conn.execute(
            "SELECT COUNT(*) FROM raw_er_activo_line WHERE activo_key=? AND periodo=? AND superseded_at IS NULL",
            (_ACTIVO_KEY, periodo),
        ).fetchone()[0]
        if existente:
            return {
                "ok": False,
                "errors": [f"Sucden {periodo} ya está ingestado ({existente} filas). Este flujo es solo hacia adelante."],
                "warnings": [],
            }

        ultimo = _ultimo_periodo(conn)
        warnings = []
        if ultimo and periodo <= ultimo:
            warnings.append(f"El último período ingestado es {ultimo}; estás ingestando {periodo} (anterior o igual).")

        valores = dict(valores_vigentes(conn))
        for codigo, monto in (overrides or {}).items():
            if codigo in valores and monto is not None:
                valores[codigo] = float(monto)

        lineas = generar_lineas(periodo, valores)
        noi_uf = sum(l["monto_clp"] for l in lineas if l["es_operacional"])
        ingresos_uf = sum(l["monto_clp"] for l in lineas if l["seccion"] == "INGRESOS_OPERACION")

        return {
            "ok": True,
            "errors": [],
            "warnings": warnings,
            "activo": _ACTIVO_KEY,
            "periodo": periodo,
            "n_filas": len(lineas),
            "noi_uf": round(noi_uf, 4),
            "ingresos_uf": round(ingresos_uf, 4),
            "valores": {codigo: {"nombre": _NOMBRES[codigo], "monto_uf": round(monto, 4)}
                        for codigo, monto in valores.items()},
        }
    finally:
        if owns_conn:
            conn.close()


def persist_periodo(periodo: str, overrides: "dict[str, float] | None" = None,
                     permanentes: "list[str] | None" = None,
                     conn: "sqlite3.Connection | None" = None) -> dict:
    """Persiste los montos de Sucden para `periodo`. Rechaza si el período ya
    tiene filas activas (protege el histórico real).

    `overrides`: {cuenta_codigo: monto_uf} a usar en vez del valor vigente.
    `permanentes`: subconjunto de las claves de `overrides` cuyo cambio debe
    quedar como nuevo default en `sucden_valores_fijos` (aplica desde el
    próximo período); las que no estén ahí son solo para este período.
    """
    from tools.db import repo_audit, repo_er_activo

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        existente = conn.execute(
            "SELECT COUNT(*) FROM raw_er_activo_line WHERE activo_key=? AND periodo=? AND superseded_at IS NULL",
            (_ACTIVO_KEY, periodo),
        ).fetchone()[0]
        if existente:
            raise ValueError(f"Sucden {periodo} ya está ingestado ({existente} filas). Este flujo es solo hacia adelante.")

        valores = dict(valores_vigentes(conn))
        overrides = overrides or {}
        permanentes = set(permanentes or [])

        for codigo in permanentes:
            if codigo in overrides and codigo in valores:
                conn.execute(
                    "UPDATE sucden_valores_fijos SET monto_uf=?, actualizado_at=datetime('now') WHERE cuenta_codigo=?",
                    (float(overrides[codigo]), codigo),
                )
                valores[codigo] = float(overrides[codigo])

        for codigo, monto in overrides.items():
            if codigo in valores and monto is not None:
                valores[codigo] = float(monto)

        lineas = generar_lineas(periodo, valores)
        file_hash = hashlib.sha256(f"sucden-fijo:{periodo}:{sorted(valores.items())}".encode()).hexdigest()
        for l in lineas:
            l["file_hash"] = file_hash

        run_id = repo_audit.start_ingest_run(
            conn, tool="ingest_er_sucden_fijo", source_file="fijo:Sucden", file_hash=file_hash,
        )
        inserted = repo_er_activo.insert_lines(conn, lineas, run_id)
        repo_audit.finish_ingest_run(
            conn, run_id, rows_in=len(lineas), rows_loaded=inserted, status="ok",
        )
        return {"status": "inserted", "rows": inserted, "file_hash": file_hash, "ingest_run_id": run_id}
    finally:
        if owns_conn:
            conn.close()
