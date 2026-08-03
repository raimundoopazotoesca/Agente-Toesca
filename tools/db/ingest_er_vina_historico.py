"""Ingesta histórica ER Viña Centro (activo, fondo TRI) → raw_er_activo_line.

Backfill ene-2018 a jul-2023, período no cubierto por ingest_er_vina.py (que
arranca ago-2023, fuente 'RAW/NOI VIÑA.xlsx' con detalle de ~70 cuentas).
Fuente: 'RAW/NOI VIÑA DB.xlsx', hoja 'Hoja1' — planilla auxiliar armada por
el usuario con categorías agregadas (no cuentas contables individuales),
**en UF** (confirmado por el usuario 2026-08-03, a diferencia de la fuente
detallada que trae CLP crudos).

Estructura fija (sin headers de sección a detectar, a diferencia de
ingest_er_vina.py): fila de fechas en la fila con más celdas tipo fecha,
columna A con las categorías desde "(+) Ingresos por Arriendos" hasta
"(-) Otros" (INGRESOS_OPERACION / GASTOS_OPERACION según prefijo +/-),
terminando en "NOI Mensual" (fila de control, no se ingesta — se recalcula
desde las categorías, igual que ingest_er_vina.py).

Idempotencia: NO usa el patrón activo_key+file_hash de ingest_er_vina.py
(ese superseed borraría datos de ago-2023+ ingestados por el otro script,
que vive en un archivo distinto). Acá el scope de reemplazo es por
source_file: solo se superseden filas de una ingesta anterior de este mismo
archivo histórico.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Optional

import openpyxl

_ACTIVO_KEY = "Viña Centro"
_SHEET_NAME = "Hoja1"
_CUTOFF_PERIODO = "2023-08"  # excluye desde acá: cubierto por ingest_er_vina.py


def _norm(s) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip())


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_planilla(xlsx_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[_SHEET_NAME]
    all_rows = list(ws.iter_rows(values_only=False))
    wb.close()

    # Fila de fechas: la que tiene más celdas tipo fecha.
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
            conn, tool="ingest_er_vina_historico",
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
    ap.add_argument("xlsx", help="Path a 'NOI VIÑA DB.xlsx'")
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
