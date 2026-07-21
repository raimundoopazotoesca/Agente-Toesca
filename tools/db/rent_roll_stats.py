"""Estadísticas de rent roll para la tabla "Resumen Performance Activos del
Fondo" de la página 2 del fact sheet PT (ver FONDOS_CFG["PT"]["page2"] en
scripts/build_factsheet.py).

Fuente única: raw_rent_roll_line (ingestada vía tools/db/ingest_rent_roll_validated).

Mapeo activo2 (nombre corto usado por JLL en el rent roll) -> grupo del fact
sheet, confirmado con el usuario 2026-07-20:
    "Torre A"    -> "Torre A S.A."
    "Inmob. CdC" -> "Inmob. Boulevard PT SpA"
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import repo_rent_roll  # noqa: E402
from tools.db.ingest_rent_roll_validated import (  # noqa: E402
    _monto_mensual_uf,
    _es_vacante,
    _clasificar_evento,
)

_ACTIVO2_LABEL = {
    "Torre A": "Torre A S.A.",
    "Inmob. CdC": "Inmob. Boulevard PT SpA",
}

def _snapshot(activo_key: str, periodo: str) -> dict:
    """{(activo2, unidad): {arrendatario, m2, renta_uf, vencimiento, tipo_activo_3}}"""
    conn = get_conn_for(str(DB_PATH))
    try:
        rows = repo_rent_roll.list_by_periodo(conn, activo_key, periodo)
        out = {}
        for r in rows:
            try:
                extra = json.loads(r["extra_json"] or "{}")
            except (TypeError, ValueError):
                extra = {}
            tipo = extra.get("tipo_activo_3")
            key = (extra.get("activo2") or "", r["unidad"])
            out[key] = {
                "arrendatario": r["arrendatario"],
                "m2": r["m2"] or 0.0,
                "renta_uf": r["renta_uf"] or 0.0,
                "vencimiento": r["vencimiento"],
                "tipo_activo_3": tipo,
            }
        return out
    finally:
        conn.close()


def _periodos_disponibles(activo_key: str) -> list[str]:
    conn = get_conn_for(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT DISTINCT periodo FROM raw_rent_roll_line "
            "WHERE activo_key=? AND superseded_at IS NULL ORDER BY periodo",
            (activo_key,),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def _meses_atras(periodo: str, n: int) -> str:
    y, m = (int(x) for x in periodo.split("-"))
    total = y * 12 + (m - 1) - n
    return f"{total // 12}-{total % 12 + 1:02d}"


def _celda(grupo: str, tipo: str, snapshot: dict) -> dict:
    filtradas = {
        k: v for k, v in snapshot.items()
        if _ACTIVO2_LABEL.get(k[0]) == grupo and v["tipo_activo_3"] == tipo
    }
    m2_util = sum(v["m2"] for v in filtradas.values() if not _es_vacante(v["arrendatario"]))
    m2_vac = sum(v["m2"] for v in filtradas.values() if _es_vacante(v["arrendatario"]))
    renta_mensual = sum(_monto_mensual_uf(v) for v in filtradas.values() if not _es_vacante(v["arrendatario"]))
    m2_total = m2_util + m2_vac
    pct_vac = round(m2_vac / m2_total * 100, 2) if m2_total else None
    return {
        "m2_utiles": round(m2_util, 1),
        "m2_vacantes": round(m2_vac, 1),
        "pct_vacancia_m2": pct_vac,
        "renta_mensual_uf": round(renta_mensual, 1),
    }


def _absorcion_ventana(activo_key: str, periodo: str, meses: int) -> dict:
    """Absorción bruta/neta (m² y UF) entre (periodo - meses) y periodo,
    caminando los períodos consecutivos que existan en DB dentro de esa
    ventana (los meses sin rent roll ingestado simplemente no aportan
    movimiento — no se interpola)."""
    disponibles = _periodos_disponibles(activo_key)
    limite_inf = _meses_atras(periodo, meses)
    ventana = sorted(p for p in disponibles if limite_inf <= p <= periodo)
    if len(ventana) < 2:
        return {"bruta_m2": None, "bruta_uf": None, "neta_m2": None, "neta_uf": None}

    bruta_m2 = bruta_uf = neta_m2 = neta_uf = 0.0
    for i in range(1, len(ventana)):
        snap_a = _snapshot(activo_key, ventana[i - 1])
        snap_b = _snapshot(activo_key, ventana[i])
        for key in set(snap_a) | set(snap_b):
            antes, ahora = snap_a.get(key), snap_b.get(key)
            ev = _clasificar_evento(antes, ahora)["evento"]
            if ev == "alta" and ahora is not None:
                bruta_m2 += ahora["m2"] or 0.0
                bruta_uf += _monto_mensual_uf(ahora)
                neta_m2 += ahora["m2"] or 0.0
                neta_uf += _monto_mensual_uf(ahora)
            elif ev == "baja" and antes is not None:
                neta_m2 -= antes["m2"] or 0.0
                neta_uf -= _monto_mensual_uf(antes)
    return {
        "bruta_m2": round(bruta_m2, 1), "bruta_uf": round(bruta_uf, 1),
        "neta_m2": round(neta_m2, 1), "neta_uf": round(neta_uf, 1),
    }


def _suma_celdas(celdas: list) -> dict:
    m2_utiles = sum(c["m2_utiles"] for c in celdas)
    m2_vacantes = sum(c["m2_vacantes"] for c in celdas)
    renta = sum(c["renta_mensual_uf"] for c in celdas)
    m2_total = m2_utiles + m2_vacantes
    pct_vac = round(m2_vacantes / m2_total * 100, 2) if m2_total else None
    return {
        "m2_utiles": round(m2_utiles, 1), "m2_vacantes": round(m2_vacantes, 1),
        "pct_vacancia_m2": pct_vac, "renta_mensual_uf": round(renta, 1),
    }


def get_perf_table(activo_key: str, periodo: str) -> dict | None:
    """Devuelve {(grupo, tipo): celda} para el período dado, más
    ("Torre A S.A.", "Total") (sub-columna del grupo, ver FONDOS_CFG["PT"]
    ["page2"]["perf_groups"]) y ("__grand_total__", "Total") para la columna
    Total final de la tabla. None si no hay rent roll ingestado para ese
    (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    grupos_tipos = {
        "Torre A S.A.": ["Oficinas", "Locales Comerciales", "Bodegas", "Estacionamientos"],
        "Inmob. Boulevard PT SpA": ["Locales Comerciales", "Bodegas", "Estacionamientos"],
    }
    out = {}
    todas_celdas = []
    for grupo, tipos in grupos_tipos.items():
        celdas_grupo = []
        for tipo in tipos:
            celda = _celda(grupo, tipo, snapshot)
            out[(grupo, tipo)] = celda
            celdas_grupo.append(celda)
            todas_celdas.append(celda)
        out[(grupo, "Total")] = _suma_celdas(celdas_grupo)
    out[("__grand_total__", "Total")] = _suma_celdas(todas_celdas)
    out["_absorcion_3m"] = _absorcion_ventana(activo_key, periodo, 3)
    out["_absorcion_12m"] = _absorcion_ventana(activo_key, periodo, 12)
    return out
