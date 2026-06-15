"""
Ingesta de datos por serie del fondo TRI desde PDFs de EEFF.

Extrae de la nota 'Cuotas emitidas':
  - Valor cuota libro por serie (A/C/I) por período
  - Cuotas suscritas por serie por período

Escribe a:
  - raw_valor_cuota_line (tipo='contable')
  - raw_cuota_en_circulacion_line
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, Optional

SERIE_NEMO = {
    "A": "CFITOERI1A",
    "C": "CFITOERI1C",
    "I": "CFITOERI1I",
}

# Meses en español → número
_MES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_cl_number(s: str) -> Optional[float]:
    """Convierte número chileno a float. "31.869,3926" → 31869.3926"""
    s = s.strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _fecha_from_texto(dia: str, mes_str: str, año: str) -> Optional[str]:
    """("31", "diciembre", "2025") → "2025-12-31" """
    mes_num = _MES_ES.get(mes_str.lower().strip())
    if not mes_num:
        return None
    try:
        return f"{int(año):04d}-{mes_num:02d}-{int(dia):02d}"
    except ValueError:
        return None


def parse_eeff_tri_notas(text: str) -> Dict[str, dict]:
    """
    Parsea texto de un PDF de EEFF TRI.

    Retorna:
        {fecha_iso: {"valor_cuota": {"A": float, "C": float, "I": float},
                     "cuotas":      {"A": float, "C": float, "I": float}}}

    Puede devolver múltiples fechas si el PDF incluye período actual + anterior.
    """
    result: Dict[str, dict] = {}

    # ── 1. Valor cuota libro por serie ──────────────────────────────────────
    # Patrón: "al DD de MES de YYYY tienen un valor cuota de $X para la Serie A,
    #          $Y para la Serie C y $Z para la Serie I"
    pat_bloque = re.compile(
        r"al\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\s+tienen\s+un\s+valor\s+cuota\s+de\s*\$\s*([\d\.,]+)"
        r"\s*para\s+la\s+Serie\s+A[,\s]*\$?\s*([\d\.,]+)\s*para\s+la\s+Serie\s+C\s+y\s*\$?\s*([\d\.,]+)"
        r"\s*para\s+la\s+Serie\s+I",
        re.IGNORECASE | re.DOTALL,
    )
    for m in pat_bloque.finditer(text):
        dia, mes_str, año = m.group(1), m.group(2), m.group(3)
        fecha = _fecha_from_texto(dia, mes_str, año)
        if not fecha:
            continue
        va = _parse_cl_number(m.group(4))
        vc = _parse_cl_number(m.group(5))
        vi = _parse_cl_number(m.group(6))
        if va and vc and vi:
            if fecha not in result:
                result[fecha] = {"valor_cuota": {}, "cuotas": {}}
            result[fecha]["valor_cuota"] = {"A": va, "C": vc, "I": vi}

    # ── 2. Cuotas suscritas por serie ────────────────────────────────────────
    # La tabla está aplanada. Buscamos entre "Cuotas emitidas" y "movimientos relevantes".
    # Series aparecen en orden A → C → I; "Suscritas\nNNN.NNN" para cada una.
    bloque_match = re.search(
        r"Cuotas\s+emitidas.*?(?=movimientos\s+relevantes|Saldo\s+al\s+Inicio|\Z)",
        text, re.IGNORECASE | re.DOTALL
    )
    if bloque_match:
        bloque = bloque_match.group(0)
        # Primera fecha en el bloque
        fecha_bloque_m = re.search(
            r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", bloque, re.IGNORECASE
        )
        fecha_cuotas = (
            _fecha_from_texto(
                fecha_bloque_m.group(1),
                fecha_bloque_m.group(2),
                fecha_bloque_m.group(3),
            )
            if fecha_bloque_m
            else None
        )

        # Extraer todos los valores de "Suscritas"
        suscritas_vals = re.findall(r"Suscritas\s*\n\s*([\d\.]+)", bloque)
        series_order = ["A", "C", "I"]
        if fecha_cuotas and len(suscritas_vals) >= 3:
            if fecha_cuotas not in result:
                result[fecha_cuotas] = {"valor_cuota": {}, "cuotas": {}}
            for i, serie in enumerate(series_order):
                val = _parse_cl_number(suscritas_vals[i])
                if val:
                    result[fecha_cuotas]["cuotas"][serie] = val

    return result


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def ingest_parsed_data(
    parsed: Dict[str, dict],
    source_file: str,
    file_hash: str,
    db_path: str,
) -> Dict[str, int]:
    """
    Escribe el resultado de parse_eeff_tri_notas a la DB.

    Retorna {"valor_cuota_insertadas": N, "cuotas_insertadas": M}.
    """
    from tools.db.connection import get_conn_for

    conn = get_conn_for(db_path)
    vc_count = 0
    cuotas_count = 0

    try:
        for fecha, data in parsed.items():
            periodo = fecha[:7]  # YYYY-MM

            # UF del día
            uf_row = conn.execute(
                "SELECT valor_clp FROM fact_uf WHERE fecha = ?", (fecha,)
            ).fetchone()
            uf_dia = uf_row[0] if uf_row else None

            # Valor cuota libro (tipo='contable')
            for serie, precio_clp in data.get("valor_cuota", {}).items():
                nemo = SERIE_NEMO.get(serie)
                if not nemo or precio_clp is None:
                    continue
                precio_uf = (precio_clp / uf_dia) if uf_dia else None
                cuotas_val = data.get("cuotas", {}).get(serie)
                conn.execute(
                    """INSERT OR IGNORE INTO raw_valor_cuota_line
                       (fondo_key, nemotecnico, fecha, tipo, precio_clp, precio_uf,
                        uf_dia, cuotas, periodo, source_file, file_hash)
                       VALUES ('TRI', ?, ?, 'contable', ?, ?, ?, ?, ?, ?, ?)""",
                    (nemo, fecha, precio_clp, precio_uf, uf_dia, cuotas_val,
                     periodo, source_file, file_hash),
                )
                vc_count += conn.execute("SELECT changes()").fetchone()[0]
                # Superseder valores CDG para la misma fecha/nemotécnico/tipo
                # (EEFF auditado tiene precedencia sobre CDG)
                conn.execute(
                    """UPDATE raw_valor_cuota_line
                       SET superseded_at = CURRENT_TIMESTAMP
                       WHERE nemotecnico = ? AND fecha = ? AND tipo = 'contable'
                         AND source_file = 'cdg_extract.xlsx'
                         AND superseded_at IS NULL""",
                    (nemo, fecha),
                )

            # Cuotas en circulación
            for serie, cuotas in data.get("cuotas", {}).items():
                nemo = SERIE_NEMO.get(serie)
                if not nemo or cuotas is None:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO raw_cuota_en_circulacion_line
                       (fondo_key, nemotecnico, fecha, cuotas, periodo,
                        source_file, file_hash)
                       VALUES ('TRI', ?, ?, ?, ?, ?, ?)""",
                    (nemo, fecha, cuotas, periodo, source_file, file_hash),
                )
                cuotas_count += conn.execute("SELECT changes()").fetchone()[0]

        conn.commit()
    finally:
        conn.close()

    return {"valor_cuota_insertadas": vc_count, "cuotas_insertadas": cuotas_count}


def ingest_eeff_tri_pdf(pdf_path: str, db_path: Optional[str] = None) -> Dict:
    """
    Función principal. Lee un PDF de EEFF TRI, extrae datos por serie, persiste.

    Args:
        pdf_path: Ruta absoluta al PDF.
        db_path:  Ruta a la DB. Si None, usa memory/agente_toesca_v2.db.

    Retorna dict con conteos y errores.
    """
    from markitdown import MarkItDown

    if db_path is None:
        db_path = str(Path(__file__).resolve().parents[2] / "memory" / "agente_toesca_v2.db")

    if not os.path.isfile(pdf_path):
        return {"error": f"Archivo no encontrado: {pdf_path}"}

    try:
        text = MarkItDown().convert(pdf_path).text_content or ""
    except Exception as e:
        return {"error": f"MarkItDown falló: {e}"}

    parsed = parse_eeff_tri_notas(text)
    if not parsed:
        return {"error": "No se encontraron datos por serie en el PDF", "periodos": []}

    file_hash = _hash_file(pdf_path)
    source_file = os.path.basename(pdf_path)
    counts = ingest_parsed_data(parsed, source_file, file_hash, db_path)

    return {
        "periodos_encontrados": sorted(parsed.keys()),
        **counts,
        "error": None,
    }
