"""Ingesta ER Sucden (fondo TRI) → raw_er_activo_line.

Lee la planilla xlsx 'RAW/NOI Sucden.xlsx' (SharePoint) con formato
categoría×mes anclado en la etiqueta 'Sucden', y persiste las líneas en
raw_er_activo_line. Idempotente por file_hash. NOI no se persiste — se
deriva como SUM(monto_clp) WHERE es_operacional=1.

activo_key fijo: 'Sucden' (activo industrial, Bodegas Maipú, sociedad
Inmobiliaria Chañarcillo Ltda). Montos en UF, guardados en monto_clp por
convención (mismo criterio que ingest_er_inmosa.py / ingest_er_apoquindo.py).

Estructura confirmada (2026-07-14) sobre RAW/NOI Sucden.xlsx, hoja 'Hoja1':
fila ancla 'Sucden' con el header de fechas en la MISMA fila (a diferencia
de INMOSA, donde el header está 2 filas arriba de la ancla), 4 filas de
categoría debajo, fila 'NOI Mensual' de control.

Regla de negocio permanente (confirmada por el usuario 2026-07-14): la
Sobretasa es fija en -140 UF desde el periodo 2026-01 en adelante,
independiente de lo que traiga la planilla fuente (que sigue trayendo un
valor recalculado obsoleto). El override se aplica DESPUÉS de la validación
de integridad NOI, así la validación sigue verificando los valores
originales de la fuente; solo el monto persistido de Sobretasa cambia.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Optional

import openpyxl


# ── Mapeo categoría planilla → pseudo-código + sección ──────────────────────
_CATEGORIAS: dict[str, dict] = {
    "ingresos por arriendos": {"codigo": "SUCDEN_ING_ARR",  "seccion": "INGRESOS_OPERACION"},
    "contribuciones":         {"codigo": "SUCDEN_CONTRIB",  "seccion": "GASTOS_OPERACION"},
    "sobretasa":               {"codigo": "SUCDEN_SOBRETASA", "seccion": "GASTOS_OPERACION"},
    "seguros":                 {"codigo": "SUCDEN_SEG",     "seccion": "GASTOS_OPERACION"},
}

_ANCLA = "sucden"
_LABEL_NOI = "noi mensual"
_ACTIVO_KEY = "Sucden"

# Override de regla de negocio: Sobretasa fija desde este periodo (inclusive).
_SOBRETASA_FIJA_DESDE = "2026-01"
_SOBRETASA_FIJA_VALOR = -140.0


def _norm(s) -> str:
    """Normaliza a lowercase, sin prefijo (+)/(-), sin espacios extra."""
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
    """Lee la planilla Sucden y devuelve filas listas para raw_er_activo_line.

    Layout esperado (ver docstring del módulo):
    - Fila ancla con label 'Sucden' en columna A y fechas en la misma fila
      (columna B en adelante).
    - 4 filas de categoría inmediatamente debajo de la ancla.
    - Fila 'NOI Mensual' al final del bloque — usada solo para validar
      integridad, nunca persistida.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    sheet_name = ws.title
    all_rows = list(ws.iter_rows(values_only=False))
    wb.close()

    # 1) Ubicar fila ancla "Sucden" (header de fechas está en la misma fila)
    ancla_idx = None
    for i, row in enumerate(all_rows):
        val = row[0].value if len(row) > 0 else None
        if _norm(val) == _ANCLA:
            ancla_idx = i
            break
    if ancla_idx is None:
        raise ValueError(f"No se encontró la fila ancla 'Sucden' en {xlsx_path}")

    ancla_row = all_rows[ancla_idx]
    period_by_col: dict[int, str] = {}
    for cell in ancla_row:
        v = cell.value
        if hasattr(v, "year") and hasattr(v, "month"):
            period_by_col[cell.column] = f"{v.year:04d}-{v.month:02d}"
    if len(period_by_col) < 3:
        raise ValueError(
            f"No se encontraron suficientes fechas en la fila ancla 'Sucden' en {xlsx_path}"
        )

    # 2) Recorrer filas debajo de la ancla hasta 'NOI Mensual'
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
            break  # fin del bloque Sucden

        if label in seen_categorias:
            continue  # fila duplicada, por si acaso

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

    # 3) Validación de integridad: suma de componentes == NOI Mensual
    for periodo, noi_esperado in noi_por_periodo.items():
        suma = suma_por_periodo.get(periodo, 0.0)
        delta = abs(suma - noi_esperado)
        if delta >= 0.01:
            raise ValueError(
                f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                f"suma de componentes={suma!r} != NOI Mensual={noi_esperado!r} (delta={delta!r})"
            )

    # 4) Override de regla de negocio: Sobretasa fija desde _SOBRETASA_FIJA_DESDE.
    #    Aplicado después de validar contra la fuente, para no romper la
    #    validación de integridad con el valor de la fuente aún vigente.
    for r in out:
        if r["cuenta_codigo"] == "SUCDEN_SOBRETASA" and r["periodo"] >= _SOBRETASA_FIJA_DESDE:
            r["monto_clp"] = _SOBRETASA_FIJA_VALOR

    return out


# ── Persistencia ─────────────────────────────────────────────────────────

def persist(xlsx_path: str,
            conn: "sqlite3.Connection | None" = None) -> dict:
    """Ingesta idempotente de la planilla ER Sucden en raw_er_activo_line.

    Comportamiento (idéntico a ingest_er_inmosa.persist):
    - Si ya existen filas activas (superseded_at IS NULL) con el mismo
      file_hash → no hace nada, retorna status 'skipped_idempotent'.
    - Si existen filas activas de una ingesta anterior (activo_key='Sucden',
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
            conn, tool="ingest_er_sucden",
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
