"""
Ingesta EEFF PT desde JSON producido por ChatGPT.

Formato esperado (los periodos aceptan YYYY-MM o YYYY-MM-DD; se guardan como YYYY-MM):
{
  "periodo": "YYYY-MM[-DD]",
  "periodo_comparativo": "YYYY-MM[-DD]" | null,
  "estados": [{"estado": "balance|resultado|flujo", "cuenta_nombre": "...", "monto_clp": N}],
  "estados_comparativos": [...]  // mismas filas del período anterior (puede ser [])
}

Escribe a raw_eeff_line. Idempotente: no duplica si ya existe el período.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from tools.db.eeff_cuenta_mapper import get_canonical_code


FONDO = "PT"


def ingest_from_json(data: dict, db_path: Optional[str] = None, source_file: str = "chatgpt_manual") -> dict:
    from tools.db.connection import get_conn, DEFAULT_DB_PATH
    actual_db = db_path or DEFAULT_DB_PATH

    conn = sqlite3.connect(actual_db)
    run_id = str(uuid.uuid4())[:8]
    inserted = 0
    skipped = 0

    def insert_period(periodo: str, filas: list, sf: str):
        nonlocal inserted, skipped
        # Idempotente: si ya existe el período (cualquier source), saltear
        existing = conn.execute(
            "SELECT COUNT(*) FROM raw_eeff_line WHERE fondo_key=? AND periodo=?",
            (FONDO, periodo)
        ).fetchone()[0]
        if existing:
            skipped += existing
            return

        for i, fila in enumerate(filas):
            nombre = fila.get("cuenta_nombre", "")
            sheet = fila.get("estado", "")
            canonical = get_canonical_code(nombre, sheet)
            conn.execute("""
                INSERT INTO raw_eeff_line
                (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
                 source_file, source_sheet, source_row, ingest_run_id, cuenta_codigo_canonical)
                VALUES (?, ?, NULL, ?, ?, NULL, ?, ?, ?, ?, ?)
            """, (
                FONDO, periodo,
                nombre,
                fila.get("monto_clp"),
                sf,
                sheet,
                i,
                run_id,
                canonical,
            ))
            inserted += 1

    # Normalizar a YYYY-MM (fecha exacta se puede reconstruir; consistente con resto de DB)
    def _to_month(p: str) -> str:
        return p[:7] if p and len(p) >= 7 else p

    periodo = _to_month(data["periodo"])
    insert_period(periodo, data.get("estados", []), source_file)

    comp = _to_month(data.get("periodo_comparativo") or "")
    comp_filas = data.get("estados_comparativos", [])
    if comp and comp_filas:
        insert_period(comp, comp_filas, source_file)

    conn.commit()
    conn.close()
    return {"insertadas": inserted, "ya_existian": skipped, "periodos": [periodo] + ([comp] if comp and comp_filas else [])}


def ingest_from_file(json_path: str, db_path: Optional[str] = None) -> dict:
    path = Path(json_path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return ingest_from_json(data, db_path=db_path, source_file=path.name)


def ingest_from_dir(dir_path: str, db_path: Optional[str] = None) -> dict:
    """Procesa todos los .json en un directorio."""
    total_ins = 0
    total_skip = 0
    archivos = sorted(Path(dir_path).glob("*.json"))
    for p in archivos:
        res = ingest_from_file(str(p), db_path=db_path)
        total_ins += res["insertadas"]
        total_skip += res["ya_existian"]
        print(f"  {p.name}: +{res['insertadas']} filas, periodos={res['periodos']}")
    return {"total_insertadas": total_ins, "total_ya_existian": total_skip, "archivos": len(archivos)}
