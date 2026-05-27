"""
Ingesta de EEFF históricos desde archivos MD (convertidos con MarkItDown).
Usa Gemini 2.5 Flash para extraer JSON estructurado y persiste en raw_eeff_line.

Soporta múltiples fondos: TRI, PT, APO.

Uso:
  python scripts/ingest_eeff.py --fondo TRI --file <md_path>     # un archivo (test)
  python scripts/ingest_eeff.py --fondo TRI --all                # todos los MD de work/eeff_ingesta/TRI/md
  python scripts/ingest_eeff.py --fondo PT --dry-run             # no persiste, solo dumpea JSON a disco
  python scripts/ingest_eeff.py --help                           # muestra opciones
"""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openai import OpenAI
from config import GEMINI_API_KEY

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "memory" / "agente_toesca.db"

import os
MODEL = os.getenv("EEFF_INGEST_MODEL", "gemini-2.5-flash-lite")

def paths_for_fondo(fondo_key: str) -> tuple[Path, Path, Path]:
    """Devuelve (md_dir, pdf_dir, json_dir) para un fondo dado."""
    base = ROOT / "work" / "eeff_ingesta" / fondo_key
    md_dir = base / "md"
    pdf_dir = base / "pdf"
    json_dir = base / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    return md_dir, pdf_dir, json_dir

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

SYSTEM_PROMPT = """Eres un experto en EEFF de fondos de inversión chilenos (CMF).
Recibirás el texto de un PDF de EEFF (convertido a Markdown). Extrae TODAS las cuentas con sus montos.

Devuelve SOLO JSON válido con esta estructura:
{
  "periodos_reportados": ["YYYY-MM-DD", ...],  // todas las fechas de corte que aparecen como columna en los estados
  "lineas": [
    {
      "section": "ESF|ER|ECP|EFE|NOTA_<n>|ANEXO_<letra>",
      "cuenta_codigo": "string opcional (nro de nota o código si existe)",
      "cuenta_nombre": "nombre exacto de la cuenta o partida",
      "subgrupo": "ej: Activo corriente, Pasivo no corriente, Patrimonio, etc. (opcional)",
      "periodo": "YYYY-MM-DD",
      "monto_clp": número en pesos (NO miles - multiplica por 1000 si el estado dice 'cifras en M$'),
      "monto_uf": número en UF si se reporta, null si no
    }
  ]
}

Reglas:
- ESF = Estado de Situación Financiera; ER = Estado de Resultados Integrales; ECP = Estado de Cambios en el Patrimonio; EFE = Estado de Flujos de Efectivo.
- Si el estado dice "Cifras en miles de pesos" o "M$", convierte: monto_clp = valor * 1000.
- Si dice "MM$" (millones), monto_clp = valor * 1000000.
- Una línea por (cuenta, periodo). Si un estado tiene 2 columnas (2018 y 2017), genera 2 líneas.
- Para notas/anexos con desglose tabular (cartera de inversiones, etc), incluye cada fila como una línea con section="NOTA_<n>" o "ANEXO_<letra>".
- Ignora encabezados de página, índices, párrafos narrativos. Solo extrae cuentas con monto numérico.
- Si un monto es vacío o "-", omite la línea.
- Negativos: respeta el signo (paréntesis = negativo).
"""

USER_PROMPT_TPL = """Archivo: {filename}

Texto del PDF:
---
{md_content}
---

Extrae todas las cuentas con sus montos en el JSON especificado. Sé exhaustivo: incluye ESF, ER, ECP, EFE, todas las notas con tablas, y anexos."""


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def extract_periodo_from_filename(name: str) -> str | None:
    """Best-effort: detecta YYYYMM o MMYYYY o DDMMYYYY del nombre. Devuelve YYYY-MM-DD del cierre."""
    # 31122018, 31032019, 31-03-2020
    m = re.search(r"(\d{2})[-]?(\d{2})[-]?(\d{4})", name)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo}-{d}"
    # 201912, 201906, 202009
    m = re.search(r"(20\d{2})(\d{2})", name)
    if m:
        y, mo = m.groups()
        # último día del mes
        from calendar import monthrange
        d = monthrange(int(y), int(mo))[1]
        return f"{y}-{mo}-{d:02d}"
    # 032018, 062018, 092018, 122018
    m = re.search(r"(\d{2})(20\d{2})", name)
    if m:
        mo, y = m.groups()
        if 1 <= int(mo) <= 12:
            from calendar import monthrange
            d = monthrange(int(y), int(mo))[1]
            return f"{y}-{mo}-{d:02d}"
    # 12.20, 06.20
    m = re.search(r"(\d{2})\.(\d{2})", name)
    if m:
        mo, yy = m.groups()
        if 1 <= int(mo) <= 12:
            y = f"20{yy}"
            from calendar import monthrange
            d = monthrange(int(y), int(mo))[1]
            return f"{y}-{mo}-{d:02d}"
    return None


def _try_repair_json(s: str) -> str:
    # quita trailing commas antes de } o ]
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    # quita líneas vacías
    return s


def call_gemini(md_text: str, filename: str, raw_dump: Path | None = None) -> dict:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TPL.format(filename=filename, md_content=md_text)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=65536,
    )
    content = resp.choices[0].message.content
    if raw_dump is not None:
        raw_dump.write_text(content, encoding="utf-8")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # intento de reparación
        return json.loads(_try_repair_json(content))


def get_pdf_for_md(md_path: Path, pdf_dir: Path) -> Path | None:
    """Encuentra el PDF/DOCX original cuyo stem coincide."""
    for ext in (".pdf", ".docx"):
        cand = pdf_dir / (md_path.stem + ext)
        if cand.exists():
            return cand
    return None


def ensure_ingest_run(con: sqlite3.Connection, source_file: str, fhash: str) -> int:
    cur = con.execute(
        "INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status) VALUES (?, ?, ?, ?, ?)",
        ("ingest_eeff_tri", source_file, fhash, datetime.now().isoformat(timespec="seconds"), "running"),
    )
    return cur.lastrowid


def insert_lines(con: sqlite3.Connection, lineas: list[dict], fondo_key: str, source_file: str, fhash: str, run_id: int):
    rows = []
    for L in lineas:
        rows.append((
            fondo_key,
            L.get("periodo"),
            L.get("cuenta_codigo"),
            L.get("cuenta_nombre"),
            L.get("monto_clp"),
            L.get("monto_uf"),
            source_file,
            L.get("section"),
            None,  # source_row
            fhash,
            run_id,
        ))
    con.executemany(
        """INSERT INTO raw_eeff_line
           (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
            source_file, source_sheet, source_row, file_hash, ingest_run_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    return len(rows)


def already_ingested(con: sqlite3.Connection, fhash: str) -> bool:
    n = con.execute(
        "SELECT COUNT(*) FROM raw_eeff_line WHERE file_hash = ? AND superseded_at IS NULL",
        (fhash,),
    ).fetchone()[0]
    return n > 0


def process_file(md_path: Path, fondo_key: str, pdf_dir: Path, json_dir: Path, dry_run: bool = False) -> dict:
    pdf = get_pdf_for_md(md_path, pdf_dir)
    if pdf is None:
        return {"file": md_path.name, "error": "PDF/DOCX original no encontrado"}
    fhash = file_hash(pdf)
    md_text = md_path.read_text(encoding="utf-8")

    print(f"[{md_path.name}] enviando a Gemini ({len(md_text)} chars)...", flush=True)
    raw_dump = json_dir / (md_path.stem + ".raw.txt")
    data = call_gemini(md_text, md_path.name, raw_dump=raw_dump)

    # dump JSON to disk for inspection
    json_out = json_dir / (md_path.stem + ".json")
    json_out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    lineas = data.get("lineas", [])
    periodos = data.get("periodos_reportados", [])
    print(f"  -> {len(lineas)} líneas extraídas, periodos: {periodos}", flush=True)

    if dry_run:
        return {"file": md_path.name, "lineas": len(lineas), "periodos": periodos, "dry_run": True}

    con = sqlite3.connect(DB_PATH)
    try:
        if already_ingested(con, fhash):
            print(f"  -> ya ingestado (file_hash existe), skip", flush=True)
            return {"file": md_path.name, "skipped": True, "file_hash": fhash}
        run_id = ensure_ingest_run(con, source_file=pdf.name, fhash=fhash)
        n = insert_lines(con, lineas, fondo_key=fondo_key, source_file=pdf.name, fhash=fhash, run_id=run_id)
        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().isoformat(timespec="seconds"), len(lineas), n, run_id),
        )
        con.commit()
        return {"file": md_path.name, "inserted": n, "periodos": periodos, "file_hash": fhash}
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fondo", required=True, choices=["TRI", "PT", "APO"], help="fondo a ingestar (TRI, PT, APO)")
    ap.add_argument("--file", help="ruta a un MD específico")
    ap.add_argument("--all", action="store_true", help="procesa todos los MD en work/eeff_ingesta/<FONDO>/md")
    ap.add_argument("--dry-run", action="store_true", help="no persiste; solo dumpea JSON")
    args = ap.parse_args()

    md_dir, pdf_dir, json_dir = paths_for_fondo(args.fondo)

    if args.file:
        files = [Path(args.file)]
    elif args.all:
        files = sorted(md_dir.glob("*.md"))
    else:
        ap.error("usar --file o --all")

    results = []
    for f in files:
        try:
            r = process_file(f, fondo_key=args.fondo, pdf_dir=pdf_dir, json_dir=json_dir, dry_run=args.dry_run)
        except Exception as e:
            r = {"file": f.name, "error": str(e)}
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)

    print("\n=== RESUMEN ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
