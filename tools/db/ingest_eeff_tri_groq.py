"""
Extractor Groq para EEFF TRI — usa LLM para parsear datos por serie desde PDFs.

Extrae de la nota 'Cuotas emitidas':
  - Valor cuota libro por serie (A/C/I) por período
  - Cuotas en circulación (TOTAL) por serie por período
  - Capital suscrito en UF por serie por período (si está disponible)

Escribe a:
  - raw_valor_cuota_line (tipo='contable')
  - raw_cuota_en_circulacion_line
  - raw_capital_suscrito_line
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

load_dotenv(encoding="utf-8")

SERIE_NEMO = {
    "A": "CFITOERI1A",
    "C": "CFITOERI1C",
    "I": "CFITOERI1I",
}

_MES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

GROQ_MODEL = "llama-3.3-70b-versatile"  # preciso para números y tablas

SYSTEM_PROMPT = """Eres un extractor de datos financieros de EEFF de fondos de inversión chilenos.
Recibes texto extraído de PDFs y debes extraer datos específicos en JSON.

REGLAS CRÍTICAS DE NÚMEROS (formato chileno):
- El PUNTO "." es separador de MILES (no decimal)
- La COMA "," es separador DECIMAL
- Ejemplos OBLIGATORIOS a seguir:
  * "26.828,5886"  → 26828.5886   (NO 26.8285886)
  * "278.882"      → 278882       (NO 278.882)
  * "1.252.928"    → 1252928      (NO 1252.928)
  * "31.869,3926"  → 31869.3926   (NO 31.8693926)
- Si un valor no está disponible, usa null
- Retorna SOLO el JSON, sin texto adicional ni markdown
"""

EXTRACT_PROMPT = """Del siguiente texto de EEFF TRI (Toesca Rentas Inmobiliarias), extrae:

1. Para CADA período mencionado (puede haber 1 o 2: actual y comparativo):
   a) fecha: "YYYY-MM-DD"
   b) valor_cuota: valor cuota libro en CLP para Series A, C e I
      (buscar "tienen un valor cuota de $X para la Serie A, $Y para la Serie C y $Z para la Serie I")
   c) cuotas_total: número TOTAL de cuotas en circulación para Series A, C e I
      (usar el valor TOTAL al final de la tabla de la nota Cuotas Emitidas, NO filas parciales)

2. Del Estado de Cambios en el Patrimonio (puede haber una tabla por serie o una tabla consolidada):
   - capital_suscrito_mclp: saldo de "Capital aportado" al CIERRE del período, POR SERIE A, C e I (M$).
     Es el saldo final de la columna "Aportes M$" o "Capital aportado" para cada serie.
     Si hay una sola tabla consolidada (sin desglose por serie), usar null para cada serie.
   - aportes_mclp: nuevos aportes recibidos en el período (fila "Aportes (+)"), total fondo (M$)
   - disminuciones_mclp: repartos de patrimonio en el período (fila "Repartos de patrimonio (-)"), total fondo (M$)
   Extraer para el período actual y comparativo.

3. De la nota "Reparto de beneficios a los aportantes" (dividendos):
   Extraer TODOS los repartos listados por serie. Para cada reparto:
   - fecha_pago: "YYYY-MM-DD" (fecha de distribución)
   - serie: "A", "C" o "I"
   - monto_por_cuota_clp: Monto por Cuota $ (en CLP, aplicar regla número chileno)
   - monto_total_mclp: Monto total distribuido (M$)
   - tipo: "definitivo" o "provisorio"
   Nota: el mismo reparto aparece repetido para los 2 períodos — incluirlo UNA SOLA VEZ.

Retorna SOLO este JSON (sin texto extra):
{
  "periodos": [
    {
      "fecha": "YYYY-MM-DD",
      "valor_cuota": {"A": null, "C": null, "I": null},
      "cuotas_total": {"A": null, "C": null, "I": null},
      "capital_suscrito_mclp": {"A": null, "C": null, "I": null},
      "aportes_mclp": null,
      "disminuciones_mclp": null
    }
  ],
  "dividendos": [
    {
      "fecha_pago": "YYYY-MM-DD",
      "serie": "A",
      "monto_por_cuota_clp": null,
      "monto_total_mclp": null,
      "tipo": "definitivo"
    }
  ]
}

TEXTO:
"""


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _extract_cuotas_section(text: str) -> str:
    """Extrae las secciones relevantes del PDF (reduce tokens al mínimo necesario).

    Incluye:
    1. Nota Cuotas Emitidas (valor cuota + cuotas en circulación)
    2. Estado de Cambios en Patrimonio (capital aportado, aportes, disminuciones)
    """
    parts = []

    # ── Sección 1: Cuotas emitidas ──────────────────────────────────────────
    m = re.search(r"tienen\s+un\s+valor\s+cuota\s+de", text, re.IGNORECASE)
    if m:
        start = max(0, m.start() - 200)
        parts.append(text[start:start + 4500])

    # ── Sección 2: Estado de Cambios en Patrimonio ──────────────────────────
    m2 = re.search(
        r"Estado.*Cambios.*Patrimonio.*?Aportes.*?\n.*?\d",
        text, re.IGNORECASE | re.DOTALL
    )
    if m2:
        start2 = max(0, m2.start() - 100)
        parts.append("\n\n--- ESTADO DE CAMBIOS EN PATRIMONIO ---\n" + text[start2:start2 + 3000])

    # ── Sección 3: Reparto de beneficios / Dividendos ───────────────────────
    # Buscar la ocurrencia que es la nota contable real (seguida de texto, no de puntos "...")
    for m3 in re.finditer(r"[Rr]eparto\s+de\s+beneficios\s+a\s+los\s+aportantes", text, re.IGNORECASE):
        snippet = text[m3.start():m3.start() + 100]
        if "..." not in snippet and "." * 5 not in snippet:  # no es entrada de índice
            parts.append("\n\n--- REPARTO DE BENEFICIOS (DIVIDENDOS) ---\n" + text[m3.start():m3.start() + 3000])
            break

    return "\n\n".join(parts) if parts else text[:5000]


def extract_with_groq(text: str) -> Optional[dict]:
    """Extrae sección relevante y envía a Groq para parseo estructurado."""
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    section = _extract_cuotas_section(text)

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": EXTRACT_PROMPT + section},
            ],
            temperature=0,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content.strip()
        # Limpiar markdown si Groq lo puso
        if raw.startswith("```"):
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip().rstrip("```").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[groq] Error: {e}")
        return None


def _parse_fecha(s: str) -> Optional[str]:
    """'2024-06-30' → '2024-06-30' (validación básica)."""
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return None


def ingest_groq_result(
    parsed: dict,
    source_file: str,
    file_hash: str,
    db_path: str,
) -> dict:
    """
    Escribe resultado de Groq a la DB.
    Retorna conteos de inserciones.
    """
    from tools.db.connection import get_conn_for

    conn = get_conn_for(db_path)
    vc_count = cuotas_count = cap_count = 0

    try:
        for periodo_data in parsed.get("periodos", []):
            fecha = _parse_fecha(periodo_data.get("fecha", ""))
            if not fecha:
                continue
            periodo = fecha[:7]

            # UF del día para precio_uf
            uf_row = conn.execute(
                "SELECT valor_clp FROM fact_uf WHERE fecha = ?", (fecha,)
            ).fetchone()
            uf_dia = uf_row[0] if uf_row else None

            valor_cuota = periodo_data.get("valor_cuota", {})
            cuotas_total = periodo_data.get("cuotas_total", {})
            capital_suscrito_mclp = periodo_data.get("capital_suscrito_mclp", {}) or {}

            for serie in ["A", "C", "I"]:
                nemo = SERIE_NEMO[serie]

                # ── Valor cuota libro ──────────────────────────────────────
                precio_clp = valor_cuota.get(serie)
                if precio_clp:
                    precio_uf = (precio_clp / uf_dia) if uf_dia else None
                    cuotas_val = cuotas_total.get(serie)
                    conn.execute(
                        """INSERT OR IGNORE INTO raw_valor_cuota_line
                           (fondo_key, nemotecnico, fecha, tipo, precio_clp, precio_uf,
                            uf_dia, cuotas, periodo, source_file, file_hash)
                           VALUES ('TRI', ?, ?, 'contable', ?, ?, ?, ?, ?, ?, ?)""",
                        (nemo, fecha, precio_clp, precio_uf, uf_dia, cuotas_val,
                         periodo, source_file, file_hash),
                    )
                    vc_count += conn.execute("SELECT changes()").fetchone()[0]
                    # Superseder CDG si EEFF tiene el mismo período
                    conn.execute(
                        """UPDATE raw_valor_cuota_line
                           SET superseded_at = CURRENT_TIMESTAMP
                           WHERE nemotecnico = ? AND fecha = ? AND tipo = 'contable'
                             AND source_file = 'cdg_extract.xlsx'
                             AND superseded_at IS NULL""",
                        (nemo, fecha),
                    )

                # ── Cuotas en circulación ──────────────────────────────────
                cuotas_n = cuotas_total.get(serie)
                if cuotas_n:
                    # Primero eliminar entradas incorrectas del regex antiguo para este PDF
                    conn.execute(
                        """DELETE FROM raw_cuota_en_circulacion_line
                           WHERE nemotecnico = ? AND fecha = ? AND file_hash = ?
                             AND source_file != 'cdg_extract.xlsx'""",
                        (nemo, fecha, file_hash),
                    )
                    conn.execute(
                        """INSERT OR IGNORE INTO raw_cuota_en_circulacion_line
                           (fondo_key, nemotecnico, fecha, cuotas, periodo,
                            source_file, file_hash)
                           VALUES ('TRI', ?, ?, ?, ?, ?, ?)""",
                        (nemo, fecha, cuotas_n, periodo, source_file, file_hash),
                    )
                    cuotas_count += conn.execute("SELECT changes()").fetchone()[0]

                # ── Capital suscrito por serie ─────────────────────────────
                cap_mclp = capital_suscrito_mclp.get(serie)
                if cap_mclp and uf_dia:
                    cap_uf = (cap_mclp * 1_000_000) / uf_dia  # M$ → CLP → UF
                    conn.execute(
                        """INSERT OR REPLACE INTO raw_capital_suscrito_line
                           (fondo_key, nemotecnico, fecha_fin_periodo, capital_suscrito_uf,
                            periodo, source_file, file_hash)
                           VALUES ('TRI', ?, ?, ?, ?, ?, ?)""",
                        (nemo, fecha, cap_uf, periodo, source_file, file_hash),
                    )
                    cap_count += conn.execute("SELECT changes()").fetchone()[0]

            # ── Capital del fondo (aportes/disminuciones del período) ──────
            # Guardar en raw_eeff_line para trazabilidad de movimientos
            cap_total = periodo_data.get("capital_total_mclp")
            aportes = periodo_data.get("aportes_mclp")
            dism = periodo_data.get("disminuciones_mclp")

            for codigo, nombre, valor_m in [
                ("CAPITAL_TOTAL", "Capital total aportado", cap_total),
                ("CAPITAL_APORTES", "Aportes de capital en el período", aportes),
                ("CAPITAL_DISMINUCIONES", "Disminuciones de capital en el período", dism),
            ]:
                if valor_m is not None and valor_m != 0:
                    valor_clp = valor_m * 1000  # M$ → CLP
                    conn.execute(
                        """INSERT OR IGNORE INTO raw_eeff_line
                           (fondo_key, periodo, cuenta_codigo, cuenta_nombre,
                            monto_clp, source_file, file_hash)
                           VALUES ('TRI', ?, ?, ?, ?, ?, ?)""",
                        (periodo, codigo, nombre, valor_clp, source_file, file_hash),
                    )
                    cap_count += conn.execute("SELECT changes()").fetchone()[0]

        # ── Dividendos ────────────────────────────────────────────────────────
        div_count = 0
        for div in parsed.get("dividendos", []):
            fecha_pago = _parse_fecha(div.get("fecha_pago", ""))
            serie = div.get("serie", "").upper()
            monto = div.get("monto_por_cuota_clp")
            nemo = SERIE_NEMO.get(serie)
            if not (fecha_pago and nemo and monto):
                continue
            conn.execute(
                """INSERT OR IGNORE INTO fact_dividendo
                   (nemotecnico, fecha_pago, monto)
                   VALUES (?, ?, ?)""",
                (nemo, fecha_pago, monto),
            )
            div_count += conn.execute("SELECT changes()").fetchone()[0]

        conn.commit()
    finally:
        conn.close()

    return {
        "valor_cuota_insertadas": vc_count,
        "cuotas_insertadas": cuotas_count,
        "capital_insertadas": cap_count,
        "dividendos_insertados": div_count,
    }


def process_pdf_groq(pdf_path: str, db_path: Optional[str] = None) -> dict:
    """
    Procesa un PDF de EEFF TRI con Groq y persiste en DB.
    """
    from markitdown import MarkItDown

    if db_path is None:
        db_path = str(Path(__file__).resolve().parents[2] / "memory" / "agente_toesca.db")

    if not os.path.isfile(pdf_path):
        return {"error": f"No encontrado: {pdf_path}"}

    ext = os.path.splitext(pdf_path)[1].lower()
    try:
        text = MarkItDown().convert(pdf_path).text_content or ""
    except Exception as e:
        return {"error": f"MarkItDown falló: {e}"}

    parsed = extract_with_groq(text)
    if not parsed or not parsed.get("periodos"):
        return {"error": "Groq no extrajo periodos", "raw": parsed}

    file_hash = _hash_file(pdf_path)
    source_file = os.path.basename(pdf_path)
    counts = ingest_groq_result(parsed, source_file, file_hash, db_path)

    return {
        "periodos": [p["fecha"] for p in parsed.get("periodos", [])],
        **counts,
        "error": None,
    }


def backfill_all_pdfs(pdf_dir: Optional[str] = None, db_path: Optional[str] = None) -> list[dict]:
    """
    Procesa todos los PDFs/DOCXs en pdf_dir con Groq.
    Por defecto usa work/eeff_ingesta/tri/pdf/.
    """
    if pdf_dir is None:
        pdf_dir = str(Path(__file__).resolve().parents[2] / "work" / "eeff_ingesta" / "tri" / "pdf")
    if db_path is None:
        db_path = str(Path(__file__).resolve().parents[2] / "memory" / "agente_toesca.db")

    results = []
    files = sorted(
        f for f in os.listdir(pdf_dir)
        if f.lower().endswith((".pdf", ".docx"))
    )
    total = len(files)
    for i, fname in enumerate(files, 1):
        path = os.path.join(pdf_dir, fname)
        print(f"[{i}/{total}] {fname}")
        result = process_pdf_groq(path, db_path)
        result["file"] = fname
        results.append(result)
        if result.get("error"):
            print(f"  ERROR: {result['error']}")
        else:
            print(f"  OK: periodos={result.get('periodos')}, "
                  f"vc={result.get('valor_cuota_insertadas')}, "
                  f"cuotas={result.get('cuotas_insertadas')}, "
                  f"cap={result.get('capital_insertadas')}")
    return results


if __name__ == "__main__":
    results = backfill_all_pdfs()
    ok = sum(1 for r in results if not r.get("error"))
    err = sum(1 for r in results if r.get("error"))
    print(f"\n=== Resumen: {ok} OK, {err} errores ===")
