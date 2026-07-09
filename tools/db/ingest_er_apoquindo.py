"""Ingesta ER Fondo Apoquindo (Apo4501, Apo4700) → raw_er_activo_line.

Lee una planilla xlsx con formato de resumen por categoría (10 conceptos por
activo por mes) y persiste las líneas en raw_er_activo_line. Idempotente por
file_hash. NOI no se persiste — se deriva.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

import openpyxl


# ── Mapeo categoría planilla → pseudo-código + sección + signo ─────────────────
# Todas las categorías son operacionales (entran al NOI).
# Incluye variantes reales observadas en raw/NOI.xlsx (SharePoint): mojibake
# de tildes (é/ó → carácter de reemplazo U+FFFD) y un typo de origen
# ("Constultores" en vez de "Constructores").
_CATEGORIAS: dict[str, dict] = {
    "ingresos por arriendos":                {"codigo": "APO_ING_ARR",   "seccion": "INGRESOS_OPERACION"},
    "gastos comunes/vacancia":               {"codigo": "APO_GC_VAC",    "seccion": "GASTOS_OPERACION"},
    "gastos comunes / vacancia":             {"codigo": "APO_GC_VAC",    "seccion": "GASTOS_OPERACION"},
    "gastos comunes vacancia":               {"codigo": "APO_GC_VAC",    "seccion": "GASTOS_OPERACION"},
    "comisión corredor":                     {"codigo": "APO_COM_CORR",  "seccion": "GASTOS_OPERACION"},
    "comision corredor":                     {"codigo": "APO_COM_CORR",  "seccion": "GASTOS_OPERACION"},
    "comisi�n corredor":                 {"codigo": "APO_COM_CORR",  "seccion": "GASTOS_OPERACION"},
    "administración":                        {"codigo": "APO_ADM",       "seccion": "GASTOS_OPERACION"},
    "administracion":                        {"codigo": "APO_ADM",       "seccion": "GASTOS_OPERACION"},
    "administraci�n":                    {"codigo": "APO_ADM",       "seccion": "GASTOS_OPERACION"},
    "provisión reparaciones":                {"codigo": "APO_PROV_REP",  "seccion": "GASTOS_OPERACION"},
    "provision reparaciones":                {"codigo": "APO_PROV_REP",  "seccion": "GASTOS_OPERACION"},
    "gastos bono + legales + otros":         {"codigo": "APO_BONOS_LEG", "seccion": "GASTOS_OPERACION"},
    "gastos bono+legales+otros":             {"codigo": "APO_BONOS_LEG", "seccion": "GASTOS_OPERACION"},
    "gastos constructores asociados":        {"codigo": "APO_CONSTRUCT", "seccion": "GASTOS_OPERACION"},
    "gastos constructores asociados (contabilidad)": {"codigo": "APO_CONSTRUCT", "seccion": "GASTOS_OPERACION"},
    "gastos constultores asociados (contabilidad)":  {"codigo": "APO_CONSTRUCT", "seccion": "GASTOS_OPERACION"},
    "gastos iva no recuperado":              {"codigo": "APO_IVA_NR",    "seccion": "GASTOS_OPERACION"},
    "gastos iva no recuperado/otros gastos": {"codigo": "APO_IVA_NR",    "seccion": "GASTOS_OPERACION"},
    "gastos iva no recuperado/ otros gastos": {"codigo": "APO_IVA_NR",   "seccion": "GASTOS_OPERACION"},
    "contribuciones":                        {"codigo": "APO_CONTRIB",   "seccion": "GASTOS_OPERACION"},
    "seguros":                               {"codigo": "APO_SEG",       "seccion": "GASTOS_OPERACION"},
}

# Split de negocio para montos que la planilla trae combinados (sin desglose
# por activo) — regla acordada 2026-07-09 con el usuario, misma proporción
# usada para la fórmula de contribuciones futuras.
_SPLIT_COMBINADO = {"Apo4700": 0.25, "Apo4501": 0.75}

# activo_key por nombre de sub-fila en la planilla
_ACTIVOS = {"4501": "Apo4501", "4700": "Apo4700"}

# Fila etiqueta "NOI Mensual" — se ignora al parsear (NOI se deriva)
_IGNORE_LABELS = {"noi mensual", "fondo apoquindo"}


def _norm(s) -> str:
    """Normaliza a lowercase sin paréntesis inicial de signo ni espacios extra."""
    if s is None:
        return ""
    txt = str(s).strip().lower()
    # remover prefijo tipo "(-) " o "(+)"
    txt = re.sub(r"^\([+\-]\)\s*", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Parser de la planilla ──────────────────────────────────────────────────────

_MES_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _parse_periodo_header(cell_value) -> Optional[str]:
    """Convierte 'dic-24', 'ene-25', un date o datetime a 'YYYY-MM'."""
    if cell_value is None:
        return None
    # Si es datetime/date (openpyxl a veces convierte)
    if hasattr(cell_value, "year") and hasattr(cell_value, "month"):
        return f"{cell_value.year:04d}-{cell_value.month:02d}"
    s = str(cell_value).strip().lower()
    m = re.match(r"^([a-zñ]{3})[-/\s]+(\d{2,4})$", s)
    if not m:
        return None
    mes_txt, yy = m.group(1), m.group(2)
    mes = _MES_ABBR.get(mes_txt)
    if mes is None:
        return None
    year = int(yy)
    if year < 100:
        year += 2000
    return f"{year:04d}-{mes:02d}"


def _detectar_activo(cell_value) -> Optional[str]:
    """'Apoquindo 4501' → 'Apo4501'. Devuelve None si no matchea."""
    if cell_value is None:
        return None
    s = str(cell_value)
    for token, key in _ACTIVOS.items():
        if token in s:
            return key
    return None


def parse_planilla(xlsx_path: str) -> list[dict]:
    """Lee la planilla y devuelve filas listas para insertar en raw_er_activo_line.

    Layout esperado:
    - Col A: etiqueta (categoría o sub-fila activo)
    - Col B..: valores mensuales, con header de meses en la primera fila que
      tenga múltiples celdas parseables como mes.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    sheet_name = ws.title
    all_rows = list(ws.iter_rows(values_only=False))
    wb.close()

    # 1) Detectar fila de header
    header_row_idx = None
    period_by_col: dict[int, str] = {}
    for i, row in enumerate(all_rows):
        candidatos = {}
        for cell in row:
            p = _parse_periodo_header(cell.value)
            if p:
                candidatos[cell.column] = p
        if len(candidatos) >= 3:
            header_row_idx = i
            period_by_col = candidatos
            break
    if header_row_idx is None:
        raise ValueError(f"No se encontró fila de header con meses en {xlsx_path}")

    # La columna de etiqueta es la inmediatamente anterior a la primera
    # columna de período (col A + col B en la planilla real de SharePoint
    # están vacías; la etiqueta vive en col C, no en col A).
    label_col_1idx = min(period_by_col.keys()) - 1
    label_col_0idx = label_col_1idx - 1

    def _label_of(row) -> object:
        return row[label_col_0idx].value if 0 <= label_col_0idx < len(row) else None

    # 2) Recorrer filas: cuando la col de etiqueta matchea una categoría, la(s)
    #    siguiente(s) fila(s) con activo dan los valores. Para Contribuciones,
    #    la propia fila de categoría puede traer un valor combinado (sin
    #    desglose por activo) — se completa con split 25/75 (regla 2026-07-09).
    out: list[dict] = []
    current_cat: Optional[dict] = None
    current_cat_row: Optional[int] = None
    current_cat_combined: dict[str, float] = {}
    current_cat_seen: dict[str, set] = {}  # periodo -> {activo_key con dato real}

    def _flush_contrib_split() -> None:
        if current_cat is None or current_cat.get("codigo") != "APO_CONTRIB":
            return
        for periodo, combinado in current_cat_combined.items():
            ya_visto = current_cat_seen.get(periodo, set())
            for activo_key, frac in _SPLIT_COMBINADO.items():
                if activo_key in ya_visto:
                    continue  # el excel ya trae el desglose real, respetarlo
                out.append({
                    "activo_key":     activo_key,
                    "periodo":        periodo,
                    "cuenta_codigo":  "APO_CONTRIB",
                    "cuenta_nombre":  f"Contribuciones (split {int(frac*100)}% s/combinado, regla 2026-07-09)",
                    "monto_clp":      combinado * frac,
                    "monto_uf":       None,
                    "seccion":        "GASTOS_OPERACION",
                    "es_operacional": 1,
                    "source_file":    xlsx_path,
                    "source_sheet":   sheet_name,
                    "source_row":     current_cat_row,
                })

    for i in range(header_row_idx + 1, len(all_rows)):
        row = all_rows[i]
        raw_label = _label_of(row)
        label = _norm(raw_label)
        if not label:
            continue
        if label in _IGNORE_LABELS:
            _flush_contrib_split()
            current_cat, current_cat_combined, current_cat_seen = None, {}, {}
            continue
        # ¿Es una categoría?
        cat_meta = _CATEGORIAS.get(label)
        if cat_meta is not None:
            _flush_contrib_split()
            current_cat = cat_meta
            current_cat_row = i + 1
            current_cat_combined, current_cat_seen = {}, {}
            # Capturar valores propios de la fila de categoría (caso Contribuciones:
            # viene un solo monto combinado, sin desglose por activo debajo).
            for col, periodo in period_by_col.items():
                cell = row[col - 1] if col - 1 < len(row) else None
                if cell is None or cell.value is None:
                    continue
                try:
                    current_cat_combined[periodo] = float(cell.value)
                except (TypeError, ValueError):
                    continue
            continue
        # ¿Es una sub-fila de activo bajo la categoría actual?
        activo_key = _detectar_activo(raw_label)
        if activo_key is None or current_cat is None:
            continue
        for col, periodo in period_by_col.items():
            # openpyxl usa 1-index; row es tupla ordenada por columna
            cell = row[col - 1] if col - 1 < len(row) else None
            if cell is None or cell.value is None:
                continue
            try:
                monto = float(cell.value)
            except (TypeError, ValueError):
                continue
            current_cat_seen.setdefault(periodo, set()).add(activo_key)
            out.append({
                "activo_key":     activo_key,
                "periodo":        periodo,
                "cuenta_codigo":  current_cat["codigo"],
                "cuenta_nombre":  str(raw_label).strip(),
                "monto_clp":      monto,
                "monto_uf":       None,
                "seccion":        current_cat["seccion"],
                "es_operacional": 1,
                "source_file":    xlsx_path,
                "source_sheet":   sheet_name,
                "source_row":     i + 1,
            })
    _flush_contrib_split()  # última categoría del archivo
    return out


# ── Persistencia ────────────────────────────────────────────────────────────

_ACTIVO_KEYS = tuple(_ACTIVOS.values())  # ('Apo4501', 'Apo4700')


def persist(xlsx_path: str,
            conn: "sqlite3.Connection | None" = None) -> dict:
    """Ingesta idempotente de la planilla ER Apoquindo en raw_er_activo_line.

    Comportamiento:
    - Si ya existen filas activas (superseded_at IS NULL) con el mismo
      file_hash → no hace nada, retorna status 'skipped_idempotent'.
    - Si existen filas activas de una ingesta anterior de este ingestor
      (mismo activo_key, otro file_hash) → las marca superseded e inserta
      las nuevas ('superseded_and_reinserted').
    - Si no hay filas previas → inserta directo ('inserted').
    """
    import sqlite3

    from tools.db import repo_audit, repo_er_activo

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        file_hash = _file_hash(xlsx_path)

        # 1) Idempotencia: ¿ya hay filas activas con este file_hash?
        prev = conn.execute(
            """SELECT 1 FROM raw_er_activo_line
                WHERE file_hash = ? AND superseded_at IS NULL
                LIMIT 1""",
            (file_hash,),
        ).fetchone()
        if prev is not None:
            return {"status": "skipped_idempotent", "rows": 0,
                    "file_hash": file_hash, "ingest_run_id": None}

        # 2) Parsear
        lines = parse_planilla(xlsx_path)
        for line in lines:
            line["file_hash"] = file_hash

        # 3) ¿Hay filas activas de una ingesta anterior (otro file_hash) para
        #    estos activos? Marcarlas superseded (una llamada por hash previo).
        placeholders = ", ".join(["?"] * len(_ACTIVO_KEYS))
        prev_hashes = conn.execute(
            f"""SELECT DISTINCT file_hash FROM raw_er_activo_line
                 WHERE activo_key IN ({placeholders})
                   AND file_hash != ?
                   AND superseded_at IS NULL""",
            (*_ACTIVO_KEYS, file_hash),
        ).fetchall()

        if prev_hashes:
            for row in prev_hashes:
                repo_er_activo.mark_superseded(conn, file_hash=row[0])
            status = "superseded_and_reinserted"
        else:
            status = "inserted"

        # 4) Registrar corrida e insertar
        run_id = repo_audit.start_ingest_run(
            conn, tool="ingest_er_apoquindo",
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
        activos = sorted({r["activo_key"] for r in rows})
        print(f"  periodos: {periodos}")
        print(f"  activos:  {activos}")
        # Mostrar NOI por activo/periodo
        from collections import defaultdict
        noi = defaultdict(float)
        for r in rows:
            noi[(r["activo_key"], r["periodo"])] += r["monto_clp"]
        print("  NOI (M$):")
        for k in sorted(noi.keys()):
            print(f"    {k[0]} {k[1]}: {noi[k]:>15,.0f}")
        return 0

    res = persist(args.xlsx)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
