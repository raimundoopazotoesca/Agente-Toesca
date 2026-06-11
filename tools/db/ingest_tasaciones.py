"""Ingesta de tasaciones y valores de adquisición desde Excel.

Uso:
    python -X utf8 -m tools.db.ingest_tasaciones ruta/al/archivo.xlsx

Hojas esperadas:
  - 'Consolidado Tasaciones': A=activo_key, B=periodo(YYYY), C=fecha, D=tasador,
      E=valor_uf, F=m², G=UF/m², H=variación%, I=tasa_dcto, J=cap_rate,
      K=ltv, L=ltc, M=leverage_fin, ..., U=notas
  - 'Adquisiciones': A=activo_key, B=fecha_adquisicion, C=precio_uf_fondo,
      D=valor_activo_100%, E=m², F=UF/m², G=%adquirido, ..., P=notas

Machalí está excluido (strip_center_machali).
"""
import sys
from pathlib import Path
import datetime

import openpyxl

from tools.db.connection import get_conn, apply_migrations, DEFAULT_DB_PATH
from tools.db import repo_tasacion, repo_audit


_EXCLUIDOS = {"strip_center_machali", "machali"}

# Mapeo de activo_key del Excel → activo_key en dim_activo
_KEY_MAP = {
    "torre_a":                                          "Torre A",
    "apoquindo_4501":                                   "Apo4501",
    "apoquindo_4700":                                   "Apo4700",
    "apoquindo_3001":                                   "Apo3001",
    "inmobiliaria_boulevard":                           "Boulevard",
    "paseo_viña_centro":                                "Viña Centro",
    "paseo_curico":                                     "Mall Curicó",
    "paseo_curico_":                                    "Mall Curicó",
    "sucden":                                           "Sucden",
    "residencia_arturo_medina":                         "Residencia Arturo Medina",
    "residencia_candil":                                "Residencia Candil",
    "residencia_colombia":                              "Residencia Colombia",
    "residencia_coventry":                              "Residencia Coventry",
    "residencia_domingo_calderon":                      "Residencia Domingo Calderón",
    "residencia_padre_errazuriz__leonardo_da_vinci":    "Residencia Padre Errázuriz",
    "ed._guardiamarina":                                "Ed. Guardiamarina",
    "ed._placilla":                                     "Ed. Placilla",
}

# ── Mapeo de columnas (índice 0-based) ───────────────────────────────────────

_TAS_COLS = {
    "activo_key":    0,
    "periodo":       1,
    "fecha":         2,
    "tasador":       3,
    "valor_uf":      4,
    "superficie_m2": 5,
    "uf_m2":         6,
    "variacion_pct": 7,
    "tasa_dcto":     8,
    "cap_rate":      9,
    "ltv":          10,
    "ltc":          11,
    "leverage_fin": 12,
    "notas":        20,   # col U
}

_ADQ_COLS = {
    "activo_key":            0,
    "fecha_adquisicion":     1,
    "precio_uf":             2,
    "valor_activo_uf":       3,
    "superficie_m2":         4,
    "uf_m2":                 5,
    "porcentaje_adquirido":  6,
    "notas":                15,   # col P
}


def _cell(row: tuple, idx: int):
    """Devuelve el valor de la celda o None si está fuera de rango."""
    try:
        val = row[idx]
    except IndexError:
        return None
    if val == "" or val is None:
        return None
    return val


def _float(row: tuple, idx: int):
    val = _cell(row, idx)
    if val is None:
        return None
    try:
        return float(str(val).replace("%", "").replace(",", ".").strip())
    except (ValueError, TypeError):
        return None


def _str(row: tuple, idx: int):
    val = _cell(row, idx)
    return str(val).strip() if val is not None else None


def _date_str(row: tuple, idx: int) -> str | None:
    """Convierte datetime o string de fecha a YYYY-MM-DD."""
    val = _cell(row, idx)
    if val is None:
        return None
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    return s[:10] if s else None


def ingest_tasaciones(path: str) -> dict:
    """Ingesta un Excel de tasaciones y adquisiciones.

    Devuelve un dict con contadores de filas procesadas.
    """
    apply_migrations(DEFAULT_DB_PATH)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    counts = {"tasaciones_ok": 0, "tasaciones_skip": 0,
              "adquisiciones_ok": 0, "adquisiciones_skip": 0, "errores": []}

    with get_conn() as conn:
        run_id = repo_audit.start_ingest_run(conn, tool="ingest_tasaciones", source_file=path, file_hash=None)

        # ── Hoja Consolidado Tasaciones ──────────────────────────────────────
        sheet_tas = next((s for s in wb.sheetnames if "tasacion" in s.lower()), None)
        if sheet_tas:
            ws = wb[sheet_tas]
            for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                raw_key    = _str(row, _TAS_COLS["activo_key"])
                periodo    = _str(row, _TAS_COLS["periodo"])
                tasador    = _str(row, _TAS_COLS["tasador"])
                if not raw_key or not periodo or not tasador:
                    counts["tasaciones_skip"] += 1
                    continue
                if raw_key.lower() in _EXCLUIDOS:
                    counts["tasaciones_skip"] += 1
                    continue
                activo_key = _KEY_MAP.get(raw_key, raw_key)
                periodo = str(periodo).strip()[:4]  # normalizar a YYYY
                try:
                    repo_tasacion.upsert_tasacion(
                        conn,
                        activo_key=activo_key,
                        periodo=periodo,
                        tasador=tasador,
                        fecha=_date_str(row, _TAS_COLS["fecha"]),
                        valor_uf=_float(row, _TAS_COLS["valor_uf"]),
                        superficie_m2=_float(row, _TAS_COLS["superficie_m2"]),
                        uf_m2=_float(row, _TAS_COLS["uf_m2"]),
                        variacion_pct=_float(row, _TAS_COLS["variacion_pct"]),
                        tasa_dcto=_float(row, _TAS_COLS["tasa_dcto"]),
                        cap_rate=_float(row, _TAS_COLS["cap_rate"]),
                        ltv=_float(row, _TAS_COLS["ltv"]),
                        ltc=_float(row, _TAS_COLS["ltc"]),
                        leverage_fin=_float(row, _TAS_COLS["leverage_fin"]),
                        notas=_str(row, _TAS_COLS["notas"]),
                        ingest_run_id=run_id,
                    )
                    counts["tasaciones_ok"] += 1
                except Exception as e:
                    counts["errores"].append(f"Tasaciones fila {i}: {e}")
        else:
            counts["errores"].append("Hoja de tasaciones no encontrada en el Excel.")

        # ── Hoja Adquisiciones ───────────────────────────────────────────────
        if "Adquisiciones" in wb.sheetnames:
            ws = wb["Adquisiciones"]
            for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                raw_key           = _str(row, _ADQ_COLS["activo_key"])
                fecha_adquisicion = _date_str(row, _ADQ_COLS["fecha_adquisicion"])
                if not raw_key:
                    counts["adquisiciones_skip"] += 1
                    continue
                if raw_key.lower() in _EXCLUIDOS:
                    counts["adquisiciones_skip"] += 1
                    continue
                activo_key = _KEY_MAP.get(raw_key, raw_key)
                # Si no hay fecha, usar solo el año de adquisición si lo hay
                if not fecha_adquisicion:
                    año = _cell(row, 12)  # col M = año_adquisición
                    if año and str(año).strip().isdigit():
                        fecha_adquisicion = f"{str(año).strip()[:4]}-01-01"
                    else:
                        counts["adquisiciones_skip"] += 1
                        continue
                try:
                    repo_tasacion.upsert_adquisicion(
                        conn,
                        activo_key=activo_key,
                        fecha_adquisicion=fecha_adquisicion,
                        precio_uf=_float(row, _ADQ_COLS["precio_uf"]),
                        valor_activo_uf=_float(row, _ADQ_COLS["valor_activo_uf"]),
                        superficie_m2=_float(row, _ADQ_COLS["superficie_m2"]),
                        uf_m2=_float(row, _ADQ_COLS["uf_m2"]),
                        porcentaje_adquirido=_float(row, _ADQ_COLS["porcentaje_adquirido"]),
                        notas=_str(row, _ADQ_COLS["notas"]) or _str(row, 7),
                        ingest_run_id=run_id,
                    )
                    counts["adquisiciones_ok"] += 1
                except Exception as e:
                    counts["errores"].append(f"Adquisiciones fila {i}: {e}")
        else:
            counts["errores"].append("Hoja 'Adquisiciones' no encontrada en el Excel.")

        total = counts["tasaciones_ok"] + counts["adquisiciones_ok"]
        repo_audit.finish_ingest_run(conn, run_id, rows_in=total, rows_loaded=total)

    wb.close()
    return counts


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -X utf8 -m tools.db.ingest_tasaciones <ruta_excel>")
        sys.exit(1)
    path = sys.argv[1]
    if not Path(path).exists():
        print(f"Archivo no encontrado: {path}")
        sys.exit(1)
    result = ingest_tasaciones(path)
    print(f"Tasaciones: {result['tasaciones_ok']} ok, {result['tasaciones_skip']} skip")
    print(f"Adquisiciones: {result['adquisiciones_ok']} ok, {result['adquisiciones_skip']} skip")
    if result["errores"]:
        print("Errores:")
        for e in result["errores"]:
            print(f"  {e}")
