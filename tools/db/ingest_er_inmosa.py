"""Ingesta ER INMOSA (fondo TRI) → raw_er_activo_line.

Lee la planilla xlsx 'RAW/NOI INMOSA.xlsx' (SharePoint) con formato
categoría×mes anclado en la etiqueta 'INMOSA', y persiste las líneas en
raw_er_activo_line. Idempotente por file_hash. NOI no se persiste — se
deriva como SUM(monto_clp) WHERE es_operacional=1.

activo_key fijo: 'INMOSA' (sin desglose por residencia individual).
Montos en UF, guardados en monto_clp por convención (mismo criterio que
ingest_er_apoquindo.py / ingest_er_pt.py).

Estructura confirmada (2026-07-14) sobre RAW/NOI INMOSA.xlsx, hoja 'Hoja1':
fila ancla 'INMOSA', 9 filas de categoría debajo (la 2a es "Ingresos por
Arriendos" duplicada — se descarta), fila 'NOI Mensual' de control.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Optional

import openpyxl


# ── Mapeo categoría planilla → pseudo-código + sección ──────────────────────
# Todas las categorías son operacionales (entran al NOI). Incluye la variante
# mojibake real observada en RAW/NOI INMOSA.xlsx (U+FFFD por tildes perdidas).
_CATEGORIAS: dict[str, dict] = {
    "ingresos por arriendos":        {"codigo": "INMOSA_ING_ARR",     "seccion": "INGRESOS_OPERACION"},
    "contribuciones":                {"codigo": "INMOSA_CONTRIB",     "seccion": "GASTOS_OPERACION"},
    "administraci�n":           {"codigo": "INMOSA_ADM",         "seccion": "GASTOS_OPERACION"},
    "administracion":                {"codigo": "INMOSA_ADM",         "seccion": "GASTOS_OPERACION"},
    "administración":                {"codigo": "INMOSA_ADM",         "seccion": "GASTOS_OPERACION"},
    "provision reparaciones":        {"codigo": "INMOSA_PROV_REP",    "seccion": "GASTOS_OPERACION"},
    "provisión reparaciones":        {"codigo": "INMOSA_PROV_REP",    "seccion": "GASTOS_OPERACION"},
    "aseo, mantenci�n y otros": {"codigo": "INMOSA_ASEO",        "seccion": "GASTOS_OPERACION"},
    "aseo, mantencion y otros":      {"codigo": "INMOSA_ASEO",        "seccion": "GASTOS_OPERACION"},
    "aseo, mantención y otros":      {"codigo": "INMOSA_ASEO",        "seccion": "GASTOS_OPERACION"},
    "otros gastos operacionales":    {"codigo": "INMOSA_OTROS_GASTOS","seccion": "GASTOS_OPERACION"},
    "iva":                           {"codigo": "INMOSA_IVA",         "seccion": "GASTOS_OPERACION"},
    "seguros":                       {"codigo": "INMOSA_SEG",         "seccion": "GASTOS_OPERACION"},
}

_ANCLA = "inmosa"
_LABEL_NOI = "noi mensual"
_ACTIVO_KEY = "INMOSA"


def _norm(s) -> str:
    """Normaliza a lowercase, sin prefijo (+)/(-), sin espacios extra al
    inicio/fin ni duplicados internos. Preserva U+FFFD (mojibake) tal cual
    para permitir matchear ambas variantes (con y sin mojibake)."""
    if s is None:
        return ""
    txt = str(s).strip().lower()
    txt = re.sub(r"^\([+\-]\)\s*", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_planilla(xlsx_path: str) -> list[dict]:
    """Lee la planilla INMOSA y devuelve filas listas para raw_er_activo_line.

    Layout esperado (ver docstring del módulo):
    - Fila ancla con label 'INMOSA' en columna A.
    - Fila de header de fechas 2 filas arriba de la ancla.
    - 9 filas de categoría inmediatamente debajo de la ancla (la 2a
      ocurrencia de "Ingresos por Arriendos" se descarta).
    - Fila 'NOI Mensual' al final del bloque — usada solo para validar
      integridad, nunca persistida.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    sheet_name = ws.title
    all_rows = list(ws.iter_rows(values_only=False))
    wb.close()

    # 1) Ubicar fila ancla "INMOSA"
    ancla_idx = None
    for i, row in enumerate(all_rows):
        val = row[0].value if len(row) > 0 else None
        if _norm(val) == _ANCLA:
            ancla_idx = i
            break
    if ancla_idx is None:
        raise ValueError(f"No se encontró la fila ancla 'INMOSA' en {xlsx_path}")

    # 2) Fila de header de fechas: buscar hacia arriba desde la ancla la
    #    primera fila con >=3 celdas parseables como fecha.
    header_row_idx = None
    period_by_col: dict[int, str] = {}
    for i in range(ancla_idx - 1, -1, -1):
        row = all_rows[i]
        candidatos = {}
        for cell in row:
            v = cell.value
            if hasattr(v, "year") and hasattr(v, "month"):
                candidatos[cell.column] = f"{v.year:04d}-{v.month:02d}"
        if len(candidatos) >= 3:
            header_row_idx = i
            period_by_col = candidatos
            break
    if header_row_idx is None:
        raise ValueError(f"No se encontró fila de header con fechas antes de la ancla 'INMOSA' en {xlsx_path}")

    # 3) Recorrer filas debajo de la ancla hasta 'NOI Mensual'
    out: list[dict] = []
    seen_categorias: set[str] = set()
    noi_por_periodo: dict[str, float] = {}
    suma_por_periodo: dict[str, float] = {}
    noi_row_found = False

    for i in range(ancla_idx + 1, len(all_rows)):
        row = all_rows[i]
        raw_label = row[0].value if len(row) > 0 else None
        label = _norm(raw_label)
        if not label:
            continue
        if label == _LABEL_NOI:
            noi_row_found = True
            for col, periodo in period_by_col.items():
                cell = row[col - 1] if col - 1 < len(row) else None
                if cell is not None and cell.value is not None:
                    noi_por_periodo[periodo] = float(cell.value)
            break  # fin del bloque INMOSA

        if label in seen_categorias:
            continue  # fila duplicada (ej. "Ingresos por Arriendos" repetida)

        cat_meta = _CATEGORIAS.get(label)
        if cat_meta is None:
            raise ValueError(
                f"Categoría no reconocida en {xlsx_path}, fila {i + 1}: {raw_label!r}"
            )
        seen_categorias.add(label)

        for col, periodo in period_by_col.items():
            cell = row[col - 1] if col - 1 < len(row) else None
            monto = float(cell.value) if cell is not None and cell.value is not None else 0.0
            suma_por_periodo[periodo] = suma_por_periodo.get(periodo, 0.0) + monto
            out.append({
                "activo_key":     _ACTIVO_KEY,
                "periodo":        periodo,
                "cuenta_codigo":  cat_meta["codigo"],
                "cuenta_nombre":  str(raw_label).strip(),
                "monto_clp":      monto,
                "monto_uf":       None,
                "seccion":        cat_meta["seccion"],
                "es_operacional": 1,
                "source_file":    xlsx_path,
                "source_sheet":   sheet_name,
                "source_row":     i + 1,
            })

    if not noi_row_found:
        raise ValueError(f"No se encontró la fila 'NOI Mensual' en {xlsx_path}")

    # 4) Validación de integridad: suma de componentes == NOI Mensual
    for periodo, noi_esperado in noi_por_periodo.items():
        suma = suma_por_periodo.get(periodo, 0.0)
        delta = abs(suma - noi_esperado)
        if delta >= 0.01:
            raise ValueError(
                f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                f"suma de componentes={suma!r} != NOI Mensual={noi_esperado!r} (delta={delta!r})"
            )

    return out


# ── Persistencia ─────────────────────────────────────────────────────────

def persist(xlsx_path: str,
            conn: "sqlite3.Connection | None" = None) -> dict:
    """Ingesta idempotente de la planilla ER INMOSA en raw_er_activo_line.

    Comportamiento (idéntico a ingest_er_apoquindo.persist):
    - Si ya existen filas activas (superseded_at IS NULL) con el mismo
      file_hash → no hace nada, retorna status 'skipped_idempotent'.
    - Si existen filas activas de una ingesta anterior (activo_key='INMOSA',
      otro file_hash) → las marca superseded e inserta las nuevas
      ('superseded_and_reinserted').
    - Si no hay filas previas → inserta directo ('inserted').
    """
    from tools.db import repo_audit, repo_er_activo

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        file_hash = _file_hash(xlsx_path)

        prev = conn.execute(
            """SELECT 1 FROM raw_er_activo_line
                WHERE file_hash = ? AND superseded_at IS NULL
                LIMIT 1""",
            (file_hash,),
        ).fetchone()
        if prev is not None:
            return {"status": "skipped_idempotent", "rows": 0,
                    "file_hash": file_hash, "ingest_run_id": None}

        lines = parse_planilla(xlsx_path)
        for line in lines:
            line["file_hash"] = file_hash

        prev_hashes = conn.execute(
            """SELECT DISTINCT file_hash FROM raw_er_activo_line
                WHERE activo_key = ?
                  AND file_hash != ?
                  AND superseded_at IS NULL""",
            (_ACTIVO_KEY, file_hash),
        ).fetchall()

        if prev_hashes:
            for row in prev_hashes:
                repo_er_activo.mark_superseded(conn, file_hash=row[0])
            status = "superseded_and_reinserted"
        else:
            status = "inserted"

        run_id = repo_audit.start_ingest_run(
            conn, tool="ingest_er_inmosa",
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


# ── CLI ───────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx", help="Path a la planilla xlsx")
    ap.add_argument("--dry-run", action="store_true",
                     help="Parsea e imprime resumen, no escribe DB")
    args = ap.parse_args(argv)

    if args.dry_run:
        rows = parse_planilla(args.xlsx)
        print(f"Parsed {len(rows)} filas de {args.xlsx}")
        periodos = sorted({r["periodo"] for r in rows})
        print(f"  periodos: {periodos[0]}..{periodos[-1]} ({len(periodos)} meses)")
        from collections import defaultdict
        noi = defaultdict(float)
        for r in rows:
            noi[r["periodo"]] += r["monto_clp"]
        print("  NOI (UF) por periodo (primeros y últimos 3):")
        for p in periodos[:3] + periodos[-3:]:
            print(f"    {p}: {noi[p]:>15,.2f}")
        return 0

    res = persist(args.xlsx)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
