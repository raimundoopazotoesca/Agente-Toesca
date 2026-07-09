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
_CATEGORIAS: dict[str, dict] = {
    "ingresos por arriendos":                {"codigo": "APO_ING_ARR",   "seccion": "INGRESOS_OPERACION"},
    "gastos comunes/vacancia":               {"codigo": "APO_GC_VAC",    "seccion": "GASTOS_OPERACION"},
    "gastos comunes / vacancia":             {"codigo": "APO_GC_VAC",    "seccion": "GASTOS_OPERACION"},
    "comisión corredor":                     {"codigo": "APO_COM_CORR",  "seccion": "GASTOS_OPERACION"},
    "comision corredor":                     {"codigo": "APO_COM_CORR",  "seccion": "GASTOS_OPERACION"},
    "administración":                        {"codigo": "APO_ADM",       "seccion": "GASTOS_OPERACION"},
    "administracion":                        {"codigo": "APO_ADM",       "seccion": "GASTOS_OPERACION"},
    "provisión reparaciones":                {"codigo": "APO_PROV_REP",  "seccion": "GASTOS_OPERACION"},
    "provision reparaciones":                {"codigo": "APO_PROV_REP",  "seccion": "GASTOS_OPERACION"},
    "gastos bono + legales + otros":         {"codigo": "APO_BONOS_LEG", "seccion": "GASTOS_OPERACION"},
    "gastos bono+legales+otros":             {"codigo": "APO_BONOS_LEG", "seccion": "GASTOS_OPERACION"},
    "gastos constructores asociados":        {"codigo": "APO_CONSTRUCT", "seccion": "GASTOS_OPERACION"},
    "gastos constructores asociados (contabilidad)": {"codigo": "APO_CONSTRUCT", "seccion": "GASTOS_OPERACION"},
    "gastos iva no recuperado":              {"codigo": "APO_IVA_NR",    "seccion": "GASTOS_OPERACION"},
    "gastos iva no recuperado/otros gastos": {"codigo": "APO_IVA_NR",    "seccion": "GASTOS_OPERACION"},
    "contribuciones":                        {"codigo": "APO_CONTRIB",   "seccion": "GASTOS_OPERACION"},
    "seguros":                               {"codigo": "APO_SEG",       "seccion": "GASTOS_OPERACION"},
}

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

    # 2) Recorrer filas: cuando A matchea una categoría, la siguiente(s) fila(s)
    #    con activo dan los valores.
    out: list[dict] = []
    current_cat: Optional[dict] = None
    for i in range(header_row_idx + 1, len(all_rows)):
        row = all_rows[i]
        label_cell = row[0]
        label = _norm(label_cell.value)
        if not label:
            continue
        if label in _IGNORE_LABELS:
            current_cat = None
            continue
        # ¿Es una categoría?
        cat_meta = _CATEGORIAS.get(label)
        if cat_meta is not None:
            current_cat = cat_meta
            continue
        # ¿Es una sub-fila de activo bajo la categoría actual?
        activo_key = _detectar_activo(label_cell.value)
        if activo_key is None or current_cat is None:
            continue
        for col, periodo in period_by_col.items():
            # openpyxl usa 1-index; row es tupla ordenada por columna
            cell = next((c for c in row if c.column == col), None)
            if cell is None or cell.value is None:
                continue
            try:
                monto = float(cell.value)
            except (TypeError, ValueError):
                continue
            out.append({
                "activo_key":     activo_key,
                "periodo":        periodo,
                "cuenta_codigo":  current_cat["codigo"],
                "cuenta_nombre":  str(label_cell.value).strip(),
                "monto_clp":      monto,
                "monto_uf":       None,
                "seccion":        current_cat["seccion"],
                "es_operacional": 1,
                "source_file":    xlsx_path,
                "source_sheet":   sheet_name,
                "source_row":     i + 1,
            })
    return out
