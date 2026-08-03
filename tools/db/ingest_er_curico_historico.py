"""Ingesta histórica ER Mall Curicó (activo, fondo TRI) → raw_er_activo_line.

Backfill ene-2020 a jul-2023, período no cubierto por ingest_er_curico.py
(que arranca ago-2023, fuente 'RAW/NOI Curico.xlsx' con detalle de cuentas).
Fuente: 'RAW/NOI VIÑA DB.xlsx', hoja 'curico' — misma planilla auxiliar de
Viña Centro, agregada al pedido del usuario 2026-08-03, categorías
agregadas **en UF**. Mall Curicó no era parte del fondo TRI antes de
ene-2020 (confirmado por el usuario) — la hoja trae esos meses en blanco a
propósito, no es un dato faltante.

Mismo criterio que ingest_er_vina_historico.py: sin headers de sección a
detectar, fila de categorías con prefijo (+)/(-) hasta "NOI Mensual"
(fila de control, no se ingesta). Idempotencia por source_file (no por
activo_key) para no pisar los datos ago-2023+ de ingest_er_curico.py, que
vive en un archivo distinto.
"""
from __future__ import annotations

from tools.db.ingest_er_vina_historico import (
    _CUTOFF_PERIODO,
    _file_hash,
    _norm,
)
import sqlite3
from typing import Optional

import openpyxl

_ACTIVO_KEY = "Mall Curicó"
_SHEET_NAME = "curico"


def parse_planilla(xlsx_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[_SHEET_NAME]
    all_rows = list(ws.iter_rows(values_only=False))
    wb.close()

    header_row_idx = None
    period_by_col: dict[int, str] = {}
    best_count = 0
    for i, row in enumerate(all_rows):
        candidatos = {}
        for cell in row:
            v = cell.value
            if hasattr(v, "year") and hasattr(v, "month"):
                candidatos[cell.column] = f"{v.year:04d}-{v.month:02d}"
        if len(candidatos) > best_count:
            best_count = len(candidatos)
            header_row_idx = i
            period_by_col = candidatos
    if header_row_idx is None or best_count == 0:
        raise ValueError(f"No se encontró fila de fechas en {xlsx_path}::{_SHEET_NAME}")

    period_by_col = {
        col: periodo for col, periodo in period_by_col.items() if periodo < _CUTOFF_PERIODO
    }

    out: list[dict] = []
    for i in range(header_row_idx + 1, len(all_rows)):
        row = all_rows[i]
        label = _norm(row[0].value if len(row) > 0 else None)
        if not label:
            continue
        if label.lower().startswith("noi mensual"):
            break
        if label.startswith("(+)"):
            seccion, es_operacional = "INGRESOS_OPERACION", 1
        elif label.startswith("(-)"):
            seccion, es_operacional = "GASTOS_OPERACION", 1
        else:
            continue

        for col, periodo in period_by_col.items():
            cell = row[col - 1] if col - 1 < len(row) else None
            if cell is None or cell.value is None:
                continue
            out.append({
                "activo_key":     _ACTIVO_KEY,
                "periodo":        periodo,
                "cuenta_codigo":  None,
                "cuenta_nombre":  label,
                "monto_clp":      None,
                "monto_uf":       float(cell.value),
                "seccion":        seccion,
                "es_operacional": es_operacional,
                "source_file":    xlsx_path,
                "source_sheet":   _SHEET_NAME,
                "source_row":     i + 1,
            })

    return out


def persist(xlsx_path: str, conn: "sqlite3.Connection | None" = None) -> dict:
    from tools.db import repo_audit, repo_er_activo

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        file_hash = _file_hash(xlsx_path)

        prev = conn.execute(
            """SELECT 1 FROM raw_er_activo_line
                WHERE file_hash = ? AND source_sheet = ? AND superseded_at IS NULL LIMIT 1""",
            (file_hash, _SHEET_NAME),
        ).fetchone()
        if prev is not None:
            return {"status": "skipped_idempotent", "rows": 0,
                    "file_hash": file_hash, "ingest_run_id": None}

        lines = parse_planilla(xlsx_path)
        for line in lines:
            line["file_hash"] = file_hash

        prev_hashes = conn.execute(
            """SELECT DISTINCT file_hash FROM raw_er_activo_line
                WHERE source_file = ? AND source_sheet = ? AND file_hash != ?
                  AND superseded_at IS NULL""",
            (xlsx_path, _SHEET_NAME, file_hash),
        ).fetchall()
        for row in prev_hashes:
            repo_er_activo.mark_superseded(conn, file_hash=row[0])
        status = "superseded_and_reinserted" if prev_hashes else "inserted"

        run_id = repo_audit.start_ingest_run(
            conn, tool="ingest_er_curico_historico",
            source_file=xlsx_path, file_hash=file_hash,
        )
        inserted = repo_er_activo.insert_lines(conn, lines, run_id)
        repo_audit.finish_ingest_run(
            conn, run_id, rows_in=len(lines), rows_loaded=inserted, status="ok",
        )

        return {"status": status, "rows": inserted,
                "file_hash": file_hash, "ingest_run_id": run_id}
    finally:
        if owns_conn:
            conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx", help="Path a 'NOI VIÑA DB.xlsx' (hoja 'curico')")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        rows = parse_planilla(args.xlsx)
        periodos = sorted({r["periodo"] for r in rows})
        print(f"Parsed {len(rows)} filas de {args.xlsx}")
        print(f"  periodos: {periodos[0]}..{periodos[-1]} ({len(periodos)} meses)")
        from collections import defaultdict
        noi = defaultdict(float)
        for r in rows:
            if r["es_operacional"]:
                noi[r["periodo"]] += r["monto_uf"]
        for p in periodos[:3] + periodos[-3:]:
            print(f"    {p}: NOI={noi[p]:>12,.1f} UF")
        return 0

    res = persist(args.xlsx)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
