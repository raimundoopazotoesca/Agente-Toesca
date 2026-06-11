"""
Parser de EEFF PDFs de PT (Toesca Rentas Inmobiliarias PT).

PT tiene SERIE ÚNICA (nemotécnico CFITRIPT-E). Extrae:
  - Valor cuota libro (tipo='contable')
  - Cuotas suscritas (raw_cuota_en_circulacion_line)

Patrón del PDF:
  "al DD de MES de YYYY tienen un valor cuota de $ X.XXX,XXXX para la Serie UNICA"
  Tabla cuotas: "Suscritas\n1.640.000"

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

from markitdown import MarkItDown

FONDO = "PT"
NEMO = "CFITRIPT-E"

_MES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_cl_number(s: str) -> Optional[float]:
    """Número chileno a float: "13.707,4350" → 13707.435. Ignora puntuación final."""
    s = s.strip().replace(" ", "").rstrip(".,;")
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
    mes = _MES_ES.get(mes_str.lower().strip())
    if not mes:
        return None
    try:
        return f"{int(año):04d}-{mes:02d}-{int(dia):02d}"
    except ValueError:
        return None


def parse_eeff_pt(text: str) -> Dict[str, dict]:
    """
    Parsea texto de un PDF de EEFF PT.

    Retorna {fecha_iso: {"valor_cuota": float, "cuotas": float}}

    Puede retornar 2 fechas si el PDF incluye período actual + anterior.
    """
    # Normalizar espacios especiales (NBSP \xa0, thin space  , etc.)
    text = text.replace('\xa0', ' ').replace(' ', ' ').replace(' ', ' ')
    result: Dict[str, dict] = {}

    # ── 1. Valor cuota libro ─────────────────────────────────────────────────
    # 2017-2022: "al DD de MES de YYYY tiene un valor cuota de\n$X.XXX,XXXX."
    # 2023-2025: "al DD de MES de YYYY tienen un valor cuota de $  X.XXX,XXXX"
    pat_vc = re.compile(
        r"al\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\s+tiene[n]?\s+un\s+valor\s+cuota\s+de"
        r"[\s\n]*\$[\s\xa0]*([\d\.\,]+)",
        re.IGNORECASE | re.DOTALL,
    )
    for m in pat_vc.finditer(text):
        fecha = _fecha_from_texto(m.group(1), m.group(2), m.group(3))
        if not fecha:
            continue
        val = _parse_cl_number(m.group(4))
        if val:
            if fecha not in result:
                result[fecha] = {}
            result[fecha]["valor_cuota"] = val

    # ── 2. Cuotas suscritas ──────────────────────────────────────────────────
    # Buscar bloque "Cuotas emitidas" … "movimientos relevantes"
    bloque_m = re.search(
        r"Cuotas\s+emitidas.*?(?=movimientos\s+relevantes|\Z)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if bloque_m:
        bloque = bloque_m.group(0)
        # Fecha del bloque (primera que aparece)
        fecha_m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", bloque, re.IGNORECASE)
        fecha_cuotas = (
            _fecha_from_texto(fecha_m.group(1), fecha_m.group(2), fecha_m.group(3))
            if fecha_m else None
        )
        # Valor de Suscritas (número debajo del header "Suscritas")
        sus_m = re.search(r"Suscritas\s*\n\s*([\d\.]+)", bloque)
        if fecha_cuotas and sus_m:
            val = _parse_cl_number(sus_m.group(1))
            if val:
                if fecha_cuotas not in result:
                    result[fecha_cuotas] = {}
                result[fecha_cuotas]["cuotas"] = val

    return result


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def ingest_eeff_pt_pdf(pdf_path: str, db_path: Optional[str] = None) -> Dict:
    """
    Procesa un PDF de EEFF PT y escribe a la DB.

    Returns:
        {"valor_cuota_insertadas": N, "cuotas_insertadas": M, "fechas": [...]}
    """
    from tools.db.connection import get_conn, DEFAULT_DB_PATH
    actual_db = db_path or DEFAULT_DB_PATH

    path = Path(pdf_path)
    if not path.exists():
        return {"error": f"No encontrado: {pdf_path}"}

    md = MarkItDown()
    try:
        text = md.convert(pdf_path).text_content
    except Exception as e:
        return {"error": f"MarkItDown: {e}"}

    parsed = parse_eeff_pt(text)
    if not parsed:
        return {"error": "Sin datos parseables", "path": pdf_path}

    file_hash = _hash_file(pdf_path)
    source_file = path.name

    conn = sqlite3.connect(actual_db)
    conn.row_factory = sqlite3.Row

    vc_ins = 0
    cq_ins = 0
    fechas_procesadas = []

    for fecha, datos in parsed.items():
        fecha_obj_str = fecha[:7]  # YYYY-MM

        # VR Contable → raw_valor_cuota_line
        if "valor_cuota" in datos:
            # Precio CLP del PDF: no disponible directamente en el texto parseado
            # (el PDF solo da el número, sin UF del día); se pone NULL precio_clp
            precio_uf = None  # PT EEFF no da el valor en UF directamente
            precio_clp = datos["valor_cuota"]  # el PDF da el valor en CLP

            existing = conn.execute("""
                SELECT 1 FROM raw_valor_cuota_line
                WHERE fondo_key=? AND nemotecnico=? AND fecha=? AND tipo='contable'
                  AND source_file NOT LIKE '%cdg%'
            """, (FONDO, NEMO, fecha)).fetchone()

            if not existing:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO raw_valor_cuota_line
                        (fondo_key, nemotecnico, fecha, tipo, precio_clp, precio_uf,
                         periodo, source_file, file_hash)
                        VALUES (?, ?, ?, 'contable', ?, ?, ?, ?, ?)
                    """, (FONDO, NEMO, fecha, precio_clp, precio_uf,
                          fecha_obj_str, source_file, file_hash))
                    vc_ins += conn.execute("SELECT changes()").fetchone()[0]
                except Exception:
                    pass

        # Cuotas → raw_cuota_en_circulacion_line
        if "cuotas" in datos:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO raw_cuota_en_circulacion_line
                    (fondo_key, nemotecnico, fecha, cuotas, periodo, source_file, file_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (FONDO, NEMO, fecha, datos["cuotas"],
                      fecha_obj_str, source_file, file_hash))
                cq_ins += conn.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass

        fechas_procesadas.append(fecha)

    conn.commit()
    conn.close()

    return {
        "valor_cuota_insertadas": vc_ins,
        "cuotas_insertadas": cq_ins,
        "fechas": sorted(fechas_procesadas),
        "source": source_file,
    }


def backfill_eeff_pt_pdfs(
    eeff_dir: Optional[str] = None,
    verbose: bool = True,
) -> Dict:
    """
    Escanea PDFs de EEFF PT y los ingesta a la DB. Idempotente.

    Busca en este orden:
      1. work/eeff_pt/           (carpeta de staging local)
      2. SharePoint Fondos/Rentas PT/EEFF/  (estructura año/trimestre)
    """
    from config import SHAREPOINT_DIR, WORK_DIR

    bases = [
        eeff_dir,
        os.path.join(WORK_DIR, "eeff_pt"),
        os.path.join(SHAREPOINT_DIR, "Fondos", "Rentas PT", "EEFF"),
    ]
    # Usar la primera que exista y tenga PDFs
    base = next(
        (b for b in bases if b and os.path.isdir(b)
         and any(Path(b).rglob("*.pdf"))),
        bases[1],  # fallback: work/eeff_pt aunque esté vacía
    )
    pdfs = sorted(
        p for p in Path(base).rglob("*.pdf")
        if not p.name.startswith("~$")
    )

    total_vc = total_cq = 0
    errores = []
    procesados = []

    for pdf in pdfs:
        res = ingest_eeff_pt_pdf(str(pdf))
        if "error" in res:
            errores.append(f"{pdf.name}: {res['error']}")
            if verbose:
                print(f"  [ERROR] {pdf.name}: {res['error']}")
        else:
            total_vc += res["valor_cuota_insertadas"]
            total_cq += res["cuotas_insertadas"]
            procesados.append(pdf.name)
            if verbose and (res["valor_cuota_insertadas"] or res["cuotas_insertadas"]):
                print(f"  [ok] {pdf.name}: VC={res['valor_cuota_insertadas']} "
                      f"CQ={res['cuotas_insertadas']} fechas={res['fechas']}")

    return {
        "pdfs_encontrados": len(pdfs),
        "valor_cuota_insertadas": total_vc,
        "cuotas_insertadas": total_cq,
        "errores": errores,
        "procesados": procesados,
    }
