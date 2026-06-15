"""Repara JSON truncado de ingesta EEFF e inserta las líneas rescatadas en la DB."""
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

FILES = [
    ("TRI", "2406 Toesca Rentas Inmobiliarias"),
    ("TRI", "2506 EEFF Fondo Toesca Rentas Inmobiliarias"),
]


def repair_json(raw: str) -> dict:
    """Intenta reparar JSON truncado cortando en el último objeto completo."""
    # Busca el último objeto completo: '    },' seguido de otro objeto
    last_complete = raw.rfind("\n    },\n    {")
    if last_complete == -1:
        last_complete = raw.rfind("\n    }\n  ]")
    if last_complete == -1:
        raise ValueError("No se encontró punto de corte válido")

    cut = last_complete + len("\n    }")
    repaired = raw[:cut] + "\n  ]\n}"
    return json.loads(repaired)


def file_hash_for(pdf_path: Path) -> str:
    h = hashlib.sha256()
    h.update(pdf_path.read_bytes())
    return h.hexdigest()


def already_ingested(con: sqlite3.Connection, fhash: str) -> bool:
    n = con.execute(
        "SELECT COUNT(*) FROM raw_eeff_line WHERE file_hash = ?", (fhash,)
    ).fetchone()[0]
    return n > 0


def insert_lines(con, lineas, fondo_key, source_file, fhash, run_id):
    rows = [
        (
            fondo_key,
            L.get("periodo"),
            L.get("cuenta_codigo"),
            L.get("cuenta_nombre"),
            L.get("monto_clp"),
            L.get("monto_uf"),
            source_file,
            L.get("section"),
            None,
            fhash,
            run_id,
        )
        for L in lineas
    ]
    con.executemany(
        """INSERT INTO raw_eeff_line
           (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
            source_file, source_sheet, source_row, file_hash, ingest_run_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    return len(rows)


def main():
    for fondo_key, stem in FILES:
        raw_path = ROOT / "work" / "eeff_ingesta" / fondo_key / "json" / f"{stem}.raw.txt"
        pdf_dir = ROOT / "work" / "eeff_ingesta" / fondo_key / "pdf"

        if not raw_path.exists():
            print(f"[{stem}] raw file not found, skip")
            continue

        # Find PDF/DOCX
        pdf = None
        for ext in (".pdf", ".docx"):
            cand = pdf_dir / (stem + ext)
            if cand.exists():
                pdf = cand
                break
        if pdf is None:
            print(f"[{stem}] PDF not found, skip")
            continue

        fhash = file_hash_for(pdf)
        con = sqlite3.connect(DB_PATH)
        try:
            if already_ingested(con, fhash):
                print(f"[{stem}] ya ingestado, skip")
                continue

            raw = raw_path.read_text(encoding="utf-8")
            print(f"[{stem}] raw size: {len(raw)} chars, repairing...")

            try:
                data = repair_json(raw)
            except Exception as e:
                print(f"[{stem}] repair failed: {e}")
                continue

            lineas = data.get("lineas", [])
            periodos = data.get("periodos_reportados", [])
            print(f"  -> {len(lineas)} líneas rescatadas, periodos: {periodos}")

            cur = con.execute(
                "INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status) VALUES (?,?,?,?,?)",
                ("repair_truncated_eeff", pdf.name, fhash, datetime.now().isoformat(timespec="seconds"), "running"),
            )
            run_id = cur.lastrowid
            n = insert_lines(con, lineas, fondo_key, pdf.name, fhash, run_id)
            con.execute(
                "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
                ("ok", datetime.now().isoformat(timespec="seconds"), len(lineas), n, run_id),
            )
            con.commit()
            print(f"  -> {n} filas insertadas OK")
        finally:
            con.close()


if __name__ == "__main__":
    main()
