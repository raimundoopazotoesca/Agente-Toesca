"""Validate/commit para ingesta web de ocupación por residencia INMOSA.

Envuelve tools/db/ingest_ocupacion_residencia.py con la misma interfaz
validate(bytes)/commit(bytes) que usan los demás flujos de /api/* en
ingesta_server.py. Sin selector de período: la planilla trae el histórico
completo de las 9 residencias en un único archivo — cada mes se sube la
versión más reciente y se reingesta completa (idempotente por file_hash).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from tools.db import ingest_ocupacion_residencia as core


def _tmp_xlsx(file_bytes: bytes, filename: str) -> str:
    suffix = Path(filename).suffix or ".xlsx"
    fd = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        fd.write(file_bytes)
        fd.flush()
    finally:
        fd.close()
    return fd.name


def status() -> dict[str, Any]:
    """Último período ya cargado en la DB, a nivel general (contexto antes de subir)."""
    from tools.db.connection import get_conn

    conn = get_conn()
    try:
        row = conn.execute(
            """SELECT MAX(r.periodo) AS ultimo_periodo, COUNT(DISTINCT r.residencia_key) AS n_residencias
                 FROM raw_ocupacion_residencia_line r
                WHERE r.superseded_at IS NULL"""
        ).fetchone()
        return {"ultimo_periodo": row[0], "n_residencias": row[1]}
    finally:
        conn.close()


def validate(file_bytes: bytes, filename: str) -> dict[str, Any]:
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            rows = core.parse_planilla(path)
        except (ValueError, KeyError) as exc:
            return {"ok": False, "errors": [str(exc)], "warnings": []}

        residencias = sorted({r["residencia_key"] for r in rows})
        periodos = sorted({r["periodo"] for r in rows})
        warnings = []
        anomalias = [
            r for r in rows
            if r["ocupacion_pct_fuente"] is not None
            and (r["ocupacion_pct_fuente"] > 1.2 or r["ocupacion_pct_fuente"] < 0)
        ]
        for a in anomalias:
            warnings.append(
                f"{a['residencia_key']} {a['periodo']}: ocupación de la fuente ({a['ocupacion_pct_fuente']!r}) "
                f"fuera de rango — se persiste recalculada desde camas ({a['ocupacion_pct']:.1%})."
            )

        resumen = [
            {
                "residencia_key": r,
                "n_meses": len([x for x in rows if x["residencia_key"] == r]),
                "desde": min(x["periodo"] for x in rows if x["residencia_key"] == r),
                "hasta": max(x["periodo"] for x in rows if x["residencia_key"] == r),
            }
            for r in residencias
        ]

        return {
            "ok": True,
            "errors": [],
            "warnings": warnings,
            "residencias": residencias,
            "desde": periodos[0], "hasta": periodos[-1],
            "filas_a_escribir": len(rows),
            "resumen": resumen,
        }
    finally:
        Path(path).unlink(missing_ok=True)


def commit(file_bytes: bytes, filename: str) -> dict[str, Any]:
    path = _tmp_xlsx(file_bytes, filename)
    try:
        try:
            result = core.persist(path)
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "status": result["status"],
            "filas_upsert": result["rows"],
        }
    finally:
        Path(path).unlink(missing_ok=True)
