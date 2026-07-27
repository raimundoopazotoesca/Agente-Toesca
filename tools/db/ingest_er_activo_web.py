"""Validate/commit para ingesta web de ER por activo (Viña Centro, Mall Curicó).

Envuelve ingest_er_vina.py / ingest_er_curico.py (que ya existían como CLI
sobre un path de archivo) con la misma interfaz validate(bytes)/commit(bytes)
que usan los demás flujos de /api/* en ingesta_server.py — sube el xlsx
completo (todo el histórico de meses que traiga), sin selector de período: el
propio archivo define qué periodos ingesta.

Cada activo nuevo que se agregue a la ingesta web debe registrarse en
_ACTIVOS con su módulo parse_planilla/persist y su activo_key en
raw_er_activo_line — no crear un endpoint aparte por activo.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from tools.db import (
    ingest_er_curico,
    ingest_er_inmosa_mensual,
    ingest_er_mensual,
    ingest_er_vina,
)

_ACTIVOS: dict[str, dict[str, Any]] = {
    "vina": {
        "activo_key": "Viña Centro",
        "modulo": ingest_er_vina,
        "modulo_mensual": ingest_er_mensual,
        "nombre": "Viña Centro",
    },
    "curico": {
        "activo_key": "Mall Curicó",
        "modulo": ingest_er_curico,
        "modulo_mensual": ingest_er_mensual,
        "nombre": "Mall Curicó",
    },
    "inmosa": {
        "activo_key": "INMOSA",
        "modulo": None,
        "modulo_mensual": ingest_er_inmosa_mensual,
        "nombre": "INMOSA",
    },
}


def activos_disponibles() -> list[str]:
    return list(_ACTIVOS.keys())


def _config(activo: str) -> dict[str, Any]:
    cfg = _ACTIVOS.get(activo)
    if cfg is None:
        raise ValueError(f"Activo no reconocido: {activo!r}. Válidos: {activos_disponibles()}")
    return cfg


def _tmp_xlsx(file_bytes: bytes, filename: str) -> str:
    suffix = Path(filename).suffix or ".xlsx"
    fd = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        fd.write(file_bytes)
        fd.flush()
    finally:
        fd.close()
    return fd.name


def periodo_status(activo: str) -> dict[str, Any]:
    """Último periodo ya ingestado en la DB para este activo (para mostrar
    contexto en la UI antes de subir un archivo nuevo)."""
    from tools.db.connection import get_conn

    cfg = _config(activo)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(periodo) AS m, COUNT(*) AS n FROM raw_er_activo_line "
            "WHERE activo_key=? AND superseded_at IS NULL",
            (cfg["activo_key"],),
        ).fetchone()
        return {"ultimo_periodo": row["m"], "n_filas": row["n"]}
    finally:
        conn.close()


def validate(activo: str, file_bytes: bytes, filename: str) -> dict[str, Any]:
    cfg = _config(activo)
    modulo = cfg["modulo"]
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            lines = modulo.parse_planilla(path)
        except ValueError as exc:
            return {"ok": False, "errors": [str(exc)], "warnings": []}

        periodos = sorted({r["periodo"] for r in lines})
        if not periodos:
            return {"ok": False, "errors": ["El archivo no contiene periodos parseables."], "warnings": []}

        noi_por_periodo: dict[str, float] = {}
        ingresos_por_periodo: dict[str, float] = {}
        for r in lines:
            monto = r["monto_uf"] if r["monto_uf"] is not None else r["monto_clp"]
            if r["es_operacional"]:
                noi_por_periodo[r["periodo"]] = noi_por_periodo.get(r["periodo"], 0.0) + monto
            if r["seccion"] == "INGRESOS_OPERACION":
                ingresos_por_periodo[r["periodo"]] = ingresos_por_periodo.get(r["periodo"], 0.0) + monto

        estado_previo = periodo_status(activo)
        warnings = []
        if estado_previo["ultimo_periodo"] and periodos[-1] < estado_previo["ultimo_periodo"]:
            warnings.append(
                f"El archivo llega solo hasta {periodos[-1]}, pero ya hay data hasta "
                f"{estado_previo['ultimo_periodo']} en la DB. Se reemplazará TODO el histórico "
                f"de {cfg['nombre']} por el de este archivo (menos meses que antes)."
            )

        ultimos = periodos[-3:]
        resumen = [
            {
                "periodo": p,
                "noi_uf": round(noi_por_periodo.get(p, 0.0), 1),
                "ingresos_uf": round(ingresos_por_periodo.get(p, 0.0), 1),
            }
            for p in ultimos
        ]

        return {
            "ok": True,
            "errors": [],
            "warnings": warnings,
            "activo": cfg["nombre"],
            "n_periodos": len(periodos),
            "periodo_inicio": periodos[0],
            "periodo_fin": periodos[-1],
            "resumen_ultimos_meses": resumen,
            "n_filas": len(lines),
        }
    finally:
        Path(path).unlink(missing_ok=True)


def commit(activo: str, file_bytes: bytes, filename: str) -> dict[str, Any]:
    cfg = _config(activo)
    modulo = cfg["modulo"]
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            res = modulo.persist(path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "activo": cfg["nombre"], **res}
    finally:
        Path(path).unlink(missing_ok=True)


# ── Ingesta mensual (planilla EEFF del mes, hoja ESTADO DE RESULTADO) ────────
# Complementa el histórico completo de arriba: esta ingesta un solo mes por
# corrida, eligiendo el período en la UI. Ver tools/db/ingest_er_mensual.py.

def periodo_status_mensual(activo: str) -> dict[str, Any]:
    return periodo_status(activo)


def validate_mensual(activo: str, periodo: str, file_bytes: bytes, filename: str) -> dict[str, Any]:
    cfg = _config(activo)
    activo_key = cfg["activo_key"]
    modulo = cfg["modulo_mensual"]
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            ultimo_disponible = modulo.ultimo_periodo_disponible(path, activo_key)
        except ValueError as exc:
            return {"ok": False, "errors": [str(exc)], "warnings": []}

        warnings = []
        if ultimo_disponible and periodo != ultimo_disponible:
            warnings.append(
                f"El archivo tiene datos hasta {ultimo_disponible}, pero estás validando {periodo}."
            )

        try:
            from tools.db.connection import get_conn
            conn = get_conn()
            try:
                lines = modulo.parse_mes(path, activo_key, periodo, conn=conn)
            finally:
                conn.close()
        except ValueError as exc:
            return {"ok": False, "errors": [str(exc)], "warnings": warnings}

        def _monto_uf(r: dict) -> float:
            return r["monto_uf"] if r["monto_uf"] is not None else r["monto_clp"]

        noi_uf = sum(_monto_uf(r) for r in lines if r["es_operacional"])
        ingresos_uf = sum(_monto_uf(r) for r in lines if r["seccion"] == "INGRESOS_OPERACION")

        return {
            "ok": True,
            "errors": [],
            "warnings": warnings,
            "activo": cfg["nombre"],
            "periodo": periodo,
            "n_filas": len(lines),
            "noi_uf": round(noi_uf, 1),
            "ingresos_uf": round(ingresos_uf, 1),
            "ultimo_periodo_disponible": ultimo_disponible,
        }
    finally:
        Path(path).unlink(missing_ok=True)


def commit_mensual(activo: str, periodo: str, file_bytes: bytes, filename: str) -> dict[str, Any]:
    cfg = _config(activo)
    activo_key = cfg["activo_key"]
    modulo = cfg["modulo_mensual"]
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            res = modulo.persist_mes(path, activo_key, periodo)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "activo": cfg["nombre"], "periodo": periodo, **res}
    finally:
        Path(path).unlink(missing_ok=True)
