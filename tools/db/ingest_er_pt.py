"""Ingesta ER Fondo PT (Torre A, Boulevard) → raw_er_activo_line.

Lee el libro NOI PT.xlsx (SharePoint/RAW) con layout fijo de 49 filas y persiste
las líneas en raw_er_activo_line. Idempotente por file_hash. NOI no se persiste
— se deriva como SUM(monto_clp) WHERE es_operacional=1.

Valores en la planilla están en UF; se guardan en monto_clp por convención
(mismo criterio que ingest_er_apoquindo.py).

Pendientes de automatización (no incluidos en esta ingesta):
- Margen Energía: calculado internamente en Toesca (urgencia: baja)
- Gasto Común Vacancia: fórmula pendiente de definición (urgencia: media)
- Seguros: fórmula pendiente de definición (urgencia: media)
- Contribuciones: se calcula con fórmula hardcoded por ahora; a futuro
  se automatizará la fuente. Torre A: (-110660042-39543299)/UF/3,
  Blvd: (-54388202-19886599)/3/UF (ambos en UF, valor fijo anual ÷ 12 mes)
"""
from __future__ import annotations

import hashlib
from typing import Optional

import openpyxl


# ── Mapeo de filas de la planilla → (activo_key, cuenta_codigo, seccion) ───────
# La planilla tiene exactamente 49 filas (row 1 = header de fechas).
# Se mapean solo las filas de activo (no los totales ni NOI Mensual).
# row_idx es 0-indexed sobre la lista de filas.
#
# Estructura:
#   R1  (idx 0) : header fechas
#   R2  (idx 1) : "(+) Ingresos por Arriendos" — total, ignorar
#   R3  (idx 2) : "(+) Ingresos Torre A S.A"  ← Torre A ingresos
#   R4-R9       : sub-arrendatarios Torre A, ignorar
#   R10 (idx 9) : "Margen Energía" Torre A — pendiente automatización
#   R11 (idx 10): "(+) Ingresos Inmobiliaria Centro de Convenciones" ← Blvd
#   R12-R26     : sub-arrendatarios + sub-ítems Blvd, ignorar
#   R27 (idx 26): "Pago Derecho Uso / Fee Asesor" ← Blvd, categoría propia
#   R28 (idx 27): "(+) Ingresos por Contribuciones" — total, ignorar
#   R29 (idx 28): "Torre A S.A" (bajo Contribuciones ingresos) ← Torre A
#   R30 (idx 29): "Inmobiliaria Centro de Convenciones" ← Blvd
#   R31 (idx 30): "(-) Administración" — total, ignorar
#   R32 (idx 31): "Torre A S.A" ← Torre A
#   R33 (idx 32): "Inmobiliaria Centro de Convenciones" ← Blvd
#   R34 (idx 33): "(-) Comision Corredor" — total, ignorar
#   R35 (idx 34): "Torre A S.A" ← Torre A
#   R36 (idx 35): "Inmobiliaria Centro de Convenciones" ← Blvd
#   R37 (idx 36): "(-) Gasto Comun Vacancia" — total, ignorar
#   R38 (idx 37): "Torre A S.A" ← Torre A
#   R39 (idx 38): "Inmobiliaria Centro de Convenciones" ← Blvd
#   R40 (idx 39): "(-) Contribuciones" — total, ignorar
#   R41 (idx 40): "Torre A S.A" ← Torre A
#   R42 (idx 41): "Inmobiliaria Centro de Convenciones" ← Blvd
#   R43 (idx 42): "(-) Seguros" — total, ignorar
#   R44 (idx 43): "Torre A S.A" ← Torre A
#   R45 (idx 44): "Inmobiliaria Centro de Convenciones" ← Blvd
#   R46 (idx 45): "(-) Gastos Adicionales" — total, ignorar
#   R47 (idx 46): "Torre A S.A" ← Torre A
#   R48 (idx 47): "Inmobiliaria Centro de Convenciones" ← Blvd
#   R49 (idx 48): "NOI Mensual" — derivado, ignorar
_ROW_MAP: list[tuple[int, str, str, str]] = [
    # (row_idx_0based, activo_key, cuenta_codigo, seccion)
    # R3  idx 2  : "(+) Ingresos Torre A S.A"
    (2,  "Torre A",   "PT_ING_ARR",    "INGRESOS_OPERACION"),
    # R11 idx 10 : "(+) Ingresos Inmobiliaria Centro de Convenciones"
    (10, "Boulevard", "PT_ING_ARR",    "INGRESOS_OPERACION"),
    # R27 idx 26 : "Pago Derecho Uso / Fee Asesor" (sólo Boulevard)
    (26, "Boulevard", "PT_FEE_ASESOR", "INGRESOS_OPERACION"),
    # R29/R30 idx 28/29: "(+) Ingresos por Contribuciones" por activo
    (28, "Torre A",   "PT_ING_CONTRIB","INGRESOS_OPERACION"),
    (29, "Boulevard", "PT_ING_CONTRIB","INGRESOS_OPERACION"),
    # R32/R33 idx 31/32: "(-) Administración"
    (31, "Torre A",   "PT_ADM",        "GASTOS_OPERACION"),
    (32, "Boulevard", "PT_ADM",        "GASTOS_OPERACION"),
    # R35/R36 idx 34/35: "(-) Comision Corredor"
    (34, "Torre A",   "PT_COM_CORR",   "GASTOS_OPERACION"),
    (35, "Boulevard", "PT_COM_CORR",   "GASTOS_OPERACION"),
    # R38/R39 idx 37/38: "(-) Gasto Comun Vacancia" — pendiente fórmula
    (37, "Torre A",   "PT_GC_VAC",     "GASTOS_OPERACION"),
    (38, "Boulevard", "PT_GC_VAC",     "GASTOS_OPERACION"),
    # R41/R42 idx 40/41: "(-) Contribuciones"
    (40, "Torre A",   "PT_CONTRIB",    "GASTOS_OPERACION"),
    (41, "Boulevard", "PT_CONTRIB",    "GASTOS_OPERACION"),
    # R44/R45 idx 43/44: "(-) Seguros" — pendiente fórmula
    (43, "Torre A",   "PT_SEG",        "GASTOS_OPERACION"),
    (44, "Boulevard", "PT_SEG",        "GASTOS_OPERACION"),
    # R47/R48 idx 46/47: "(-) Gastos Adicionales"
    (46, "Torre A",   "PT_GAST_ADIC",  "GASTOS_OPERACION"),
    (47, "Boulevard", "PT_GAST_ADIC",  "GASTOS_OPERACION"),
    # Ignorados: R1 header, R2/R11/R28/R31/R34/R37/R40/R43/R46 totales,
    #            R4-R10 sub-arrendatarios Torre A (R10=Margen Energía, pendiente),
    #            R12-R26 sub-ítems Boulevard (R26=Margen Energía, pendiente),
    #            R49 NOI Mensual (derivado)
]


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_planilla(xlsx_path: str) -> list[dict]:
    """Lee NOI PT.xlsx y devuelve filas para insertar en raw_er_activo_line."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    sheet_name = ws.title
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Fila 0 (R1): header con fechas datetime en col B onwards
    header_row = rows[0]
    # col 0 = etiqueta, col 1+ = meses
    period_by_col: dict[int, str] = {}
    for col_idx, cell_val in enumerate(header_row):
        if col_idx == 0:
            continue
        if hasattr(cell_val, "year") and hasattr(cell_val, "month"):
            period_by_col[col_idx] = f"{cell_val.year:04d}-{cell_val.month:02d}"

    if not period_by_col:
        raise ValueError(f"No se encontraron fechas en la fila 1 de {xlsx_path}")

    out: list[dict] = []
    for row_idx, activo_key, cuenta_codigo, seccion in _ROW_MAP:
        if row_idx >= len(rows):
            continue
        row = rows[row_idx]
        for col_idx, periodo in period_by_col.items():
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if val is None:
                continue
            try:
                monto = float(val)
            except (TypeError, ValueError):
                continue
            out.append({
                "activo_key":    activo_key,
                "periodo":       periodo,
                "cuenta_codigo": cuenta_codigo,
                "cuenta_nombre": str(rows[row_idx][0]).strip() if rows[row_idx][0] else cuenta_codigo,
                "monto_clp":     monto,
                "monto_uf":      None,
                "seccion":       seccion,
                "es_operacional": 1,
                "source_file":   xlsx_path,
                "source_sheet":  sheet_name,
                "source_row":    row_idx + 1,
            })

    return out


def ingest(
    xlsx_path: str,
    conn,
    dry_run: bool = False,
) -> dict:
    """Persiste las líneas en raw_er_activo_line. Devuelve resumen."""
    from tools.db import repo_audit, repo_er_activo

    fhash = _file_hash(xlsx_path)

    # Idempotencia: skip si ya existe el mismo hash sin superseder
    cur = conn.execute(
        "SELECT COUNT(*) FROM raw_er_activo_line WHERE file_hash=? AND superseded_at IS NULL",
        (fhash,),
    )
    if cur.fetchone()[0] > 0:
        return {"status": "skipped_idempotent", "file_hash": fhash}

    lines = parse_planilla(xlsx_path)
    if not lines:
        return {"status": "no_data", "file_hash": fhash}

    if dry_run:
        return {
            "status":    "dry_run",
            "lines":     len(lines),
            "periodos":  sorted({l["periodo"] for l in lines}),
            "file_hash": fhash,
        }

    # Supersede versiones anteriores de estos activos PT
    activos_pt = {"Torre A", "Boulevard"}
    cur2 = conn.execute(
        "SELECT DISTINCT file_hash FROM raw_er_activo_line "
        "WHERE activo_key IN ('Torre A','Boulevard') AND superseded_at IS NULL "
        "  AND file_hash != ?",
        (fhash,),
    )
    for (old_hash,) in cur2.fetchall():
        repo_er_activo.mark_superseded(conn, old_hash)

    run_id = repo_audit.start_ingest_run(
        conn, tool="ingest_er_pt", source_file=xlsx_path, file_hash=fhash
    )
    for line in lines:
        line["file_hash"] = fhash
        line["ingest_run_id"] = run_id
    inserted = repo_er_activo.insert_lines(conn, lines, run_id)
    repo_audit.finish_ingest_run(conn, run_id, rows_in=len(lines), rows_loaded=inserted)
    conn.commit()

    return {
        "status":    "inserted",
        "lines":     len(lines),
        "periodos":  sorted({l["periodo"] for l in lines}),
        "file_hash": fhash,
    }


if __name__ == "__main__":
    import sys
    from tools.db.connection import get_conn

    if len(sys.argv) < 2:
        print("Uso: python -m tools.db.ingest_er_pt <ruta_NOI_PT.xlsx> [--dry-run]")
        sys.exit(1)

    path = sys.argv[1]
    dry = "--dry-run" in sys.argv

    conn = get_conn()
    result = ingest(path, conn, dry_run=dry)
    print(result)
    conn.close()
