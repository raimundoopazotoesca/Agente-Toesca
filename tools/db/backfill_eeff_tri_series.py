"""
Backfill de raw_valor_cuota_line (tipo=contable) y raw_cuota_en_circulacion_line
para el fondo TRI, combinando dos fuentes:

1. PDFs disponibles en TRI_EEFF_FONDO_DIR (SharePoint local).
2. raw_eeff_line — filas "Valor libro cuota Serie A/C/I" (cobertura 2017-2018).
"""
from __future__ import annotations

import calendar
import os
import sqlite3
from pathlib import Path

from tools.sharepoint_paths import TRI_EEFF_FONDO_DIR
from tools.db.ingest_eeff_tri_series import ingest_eeff_tri_pdf, SERIE_NEMO

DB_PATH = str(Path(__file__).resolve().parents[2] / "memory" / "agente_toesca.db")


def backfill_from_pdfs() -> list[dict]:
    """Procesa todos los PDFs encontrados en TRI_EEFF_FONDO_DIR recursivamente."""
    results = []
    seen_hashes = set()  # evitar procesar el mismo archivo dos veces (mismo PDF en 2T y 4T)

    for root, _, files in os.walk(TRI_EEFF_FONDO_DIR):
        for fname in sorted(files):
            if not fname.lower().endswith(".pdf"):
                continue
            pdf_path = os.path.join(root, fname)
            result = ingest_eeff_tri_pdf(pdf_path, DB_PATH)
            result["file"] = fname
            result["path"] = pdf_path
            results.append(result)
            print(f"[backfill_pdf] {fname}: {result}")

    return results


def backfill_from_raw_eeff_line() -> dict:
    """
    NOTA: Esta función está deshabilitada.

    Los valores de 'Valor libro cuota Serie X' en raw_eeff_line para 2017-2018
    tienen un error de parsing del PDF (factor ~10,000x respecto al valor real).
    Por ejemplo: raw_eeff_line tiene 272,119,411 CLP pero el valor correcto es
    27,211.94 CLP/cuota (de cdg_extract.xlsx).

    Para períodos 2017-2018, usar los valores de cdg_extract.xlsx que son correctos.
    Para períodos 2024+, usar backfill_from_pdfs().
    """
    print("[backfill_raw_eeff] Deshabilitado — valores históricos 2017-2018 tienen error de escala.")
    return {"insertadas": 0}


if __name__ == "__main__":
    print("=== Backfill desde PDFs ===")
    backfill_from_pdfs()
    print("\n=== Backfill desde raw_eeff_line ===")
    backfill_from_raw_eeff_line()
