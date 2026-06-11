"""
Ingesta un JSON pre-generado (ej. por ChatGPT) directamente a raw_eeff_line.

Uso:
  python scripts/ingest_from_json.py --fondo TRI --json <path.json>
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fondo", required=True, choices=["TRI", "PT", "APO"])
    ap.add_argument("--json", required=True, help="ruta al JSON generado externamente")
    ap.add_argument("--pdf", help="ruta al PDF original (para file_hash); si no se da, usa el JSON como source")
    args = ap.parse_args()

    json_path = Path(args.json)
    data = json.loads(json_path.read_text(encoding="utf-8"))

    lineas = data.get("lineas", [])
    periodos = data.get("periodos_reportados", [])
    print(f"JSON: {len(lineas)} líneas, periodos: {periodos}")

    # file_hash: preferir PDF original, sino hash del JSON
    source_ref = json_path
    if args.pdf:
        source_ref = Path(args.pdf)
    fhash = hashlib.sha256(source_ref.read_bytes()).hexdigest()
    source_file = source_ref.name

    con = sqlite3.connect(DB_PATH)
    try:
        existing = con.execute(
            "SELECT COUNT(*) FROM raw_eeff_line WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing > 0:
            print(f"Ya ingresado ({existing} filas con este hash), abortando.")
            return

        cur = con.execute(
            "INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status) VALUES (?,?,?,?,?)",
            ("ingest_from_json", source_file, fhash, datetime.now().isoformat(timespec="seconds"), "running"),
        )
        run_id = cur.lastrowid

        rows = [
            (
                args.fondo,
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
        n = len(rows)
        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().isoformat(timespec="seconds"), len(lineas), n, run_id),
        )
        con.commit()
        print(f"Insertadas {n} filas OK. Periodos: {periodos}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
