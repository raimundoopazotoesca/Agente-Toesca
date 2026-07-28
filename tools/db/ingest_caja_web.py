"""Validate/commit para ingesta web de saldo caja consolidado por fondo.

Envuelve tools/db/ingest_caja.py (CLI ya existente) con la misma interfaz
validate(bytes)/commit(bytes) que usan los demás flujos de /api/* en
ingesta_server.py. A diferencia del CLI (que por defecto recalcula todo el
histórico), acá el usuario elige un período (YYYY-MM) y solo se recalcula
ese mes — se le pasa como desde=hasta=periodo a ingest_caja.ingestar(), que
ya soporta acotar el rango.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from tools.db import ingest_caja


def _tmp_xlsx(file_bytes: bytes, filename: str) -> str:
    suffix = Path(filename).suffix or ".xlsx"
    fd = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        fd.write(file_bytes)
        fd.flush()
    finally:
        fd.close()
    return fd.name


def periodo_status() -> dict[str, Any]:
    """Última fecha ya cargada en raw_caja por fondo (contexto antes de subir)."""
    from tools.db.connection import get_conn

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT fondo_key, MAX(fecha) AS ultima_fecha, COUNT(*) AS n_meses "
            "FROM raw_caja GROUP BY fondo_key ORDER BY fondo_key"
        ).fetchall()
        return {"fondos": [dict(r) for r in rows]}
    finally:
        conn.close()


def _resumen_periodo(totales_por_periodo: dict[str, dict], periodo: str) -> dict | None:
    row = totales_por_periodo.get(periodo)
    if row is None:
        return None
    return {
        "periodo": periodo,
        "fecha_cierre": row["fecha_cierre"],
        "fecha_hoja": row["fecha_hoja"],
        "tri_clp": row.get("TRI_clp"),
        "pt_clp": row.get("PT_clp"),
        "apo_clp": row.get("Apo_clp"),
    }


def validate(periodo: str, file_bytes: bytes, filename: str) -> dict[str, Any]:
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            result = ingest_caja.ingestar(path=path, desde=periodo, hasta=periodo, dry_run=True)
        except ValueError as exc:
            return {"ok": False, "errors": [str(exc)], "warnings": []}

        if not result["meses_procesados"]:
            return {"ok": False, "errors": [f"El archivo no tiene ninguna hoja cercana al cierre de {periodo}."], "warnings": []}

        warnings = []
        faltantes = result["sociedades_faltantes"].get(periodo)
        if faltantes:
            warnings.append(
                f"Fondo(s) incompleto(s) para {periodo} (sociedad no encontrada en la hoja de ese "
                f"mes, no se actualizan): {faltantes}"
            )
        usd_fallback = result["usd_convertido_con_fallback"].get(periodo)
        if usd_fallback:
            warnings.append(
                f"Sin dólar real para la fecha de la hoja: el saldo USD de {list(usd_fallback)} se "
                f"convirtió con dólar fijo={ingest_caja.FALLBACK_USD_CLP:g}."
            )

        resumen = _resumen_periodo(result["totales_por_periodo"], periodo)
        return {
            "ok": True,
            "errors": [],
            "warnings": warnings,
            "periodo": periodo,
            "resumen": resumen,
            "filas_a_escribir": result["filas_upsert"],
        }
    finally:
        Path(path).unlink(missing_ok=True)


def commit(periodo: str, file_bytes: bytes, filename: str) -> dict[str, Any]:
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            result = ingest_caja.ingestar(path=path, desde=periodo, hasta=periodo, dry_run=False)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not result["meses_procesados"]:
            return {"ok": False, "error": f"El archivo no tiene ninguna hoja cercana al cierre de {periodo}."}
        return {
            "ok": True,
            "periodo": periodo,
            "filas_upsert": result["filas_upsert"],
            "resumen": _resumen_periodo(result["totales_por_periodo"], periodo),
            "sociedades_faltantes": result["sociedades_faltantes"].get(periodo),
            "usd_convertido_con_fallback": result["usd_convertido_con_fallback"].get(periodo),
        }
    finally:
        Path(path).unlink(missing_ok=True)
