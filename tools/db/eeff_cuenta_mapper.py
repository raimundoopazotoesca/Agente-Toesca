"""
Mapeo de nombres de cuentas EEFF a códigos canónicos.

Problema: raw_eeff_line.cuenta_nombre tiene ~1046 variantes únicas por encoding
roto, sufijos "(+ o -)", breakdowns trimestrales de APO, etc. Este módulo
normaliza los nombres y los mapea a un código estable (ej. 'ER.ingreso_arriendo').

Uso:
    from tools.db.eeff_cuenta_mapper import get_canonical_code, backfill_db
    code = get_canonical_code("Ingreso por arriendo de bienes raíces (+)", "ER")
    # → 'ER.ingreso_arriendo'
"""

import re
import unicodedata
from pathlib import Path
from functools import lru_cache

import yaml

_MAP_PATH = Path(__file__).parent.parent.parent / "config" / "cuenta_eeff_map.yaml"


@lru_cache(maxsize=1)
def _load_map() -> dict:
    with open(_MAP_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_nombre(nombre: str) -> str:
    """Normaliza un nombre de cuenta para comparación robusta."""
    if not nombre:
        return ""
    s = nombre
    # Fix encoding roto latin-1 mal interpretado como UTF-8: Ã­ → í
    try:
        s = s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    # Colapsar espacios múltiples (PDFs con espacios extra)
    s = re.sub(r"\s+", " ", s).strip()
    # Strip acentos vía NFKD → ascii
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().strip()
    # Eliminar sufijos de signo: "(+)", "(-)", "(+ o -)", "(+ ó -)" y variantes
    s = re.sub(r"\s*\(\+?\s*[oa]?\s*-?\s*\)\s*$", "", s)
    s = re.sub(r"\s*\([+-]\)\s*$", "", s)
    # Eliminar calificadores de hoja como "- actividades de operación"
    s = re.sub(r"\s*-\s*actividades\s+de\s+\w+\s*$", "", s, flags=re.IGNORECASE)
    # Eliminar breakdowns trimestrales de APO: "- Trimestre abril-junio"
    s = re.sub(r"\s*-\s*(trimestre|trimestral)\s.*$", "", s, flags=re.IGNORECASE)
    # Eliminar fechas de breakdown: "- trimestre 01/04/2019 a 30/06/2019"
    s = re.sub(r"\s*-\s*trimestre\s+\d{2}/\d{2}/\d{4}.*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def get_canonical_code(cuenta_nombre: str, source_sheet: str | None = None) -> str | None:
    """
    Retorna el código canónico para un nombre de cuenta, o None si no hay mapeo.

    Args:
        cuenta_nombre: Nombre tal como aparece en la DB.
        source_sheet: Hoja de origen (ER, ESF, EFE, ECP). Filtra para evitar
                      colisiones de nombres entre hojas.
    """
    if not cuenta_nombre:
        return None

    norm = normalize_nombre(cuenta_nombre)
    mapping = _load_map()

    for codigo, entry in mapping.items():
        if source_sheet and entry.get("source_sheet") and entry["source_sheet"] != source_sheet:
            continue
        for pattern in entry.get("patterns", []):
            if norm == pattern or norm.startswith(pattern):
                return codigo

    return None


def backfill_db(db_path: str, dry_run: bool = False) -> dict:
    """
    Aplica el mapeo a todos los rows de raw_eeff_line donde cuenta_codigo_canonical IS NULL.

    Returns:
        {'total': int, 'mapped': int, 'unmapped': int}
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT id, cuenta_nombre, source_sheet FROM raw_eeff_line "
        "WHERE cuenta_codigo_canonical IS NULL AND cuenta_nombre IS NOT NULL"
    )
    rows = cur.fetchall()

    updates = []
    unmapped = []
    for row_id, nombre, sheet in rows:
        code = get_canonical_code(nombre, sheet)
        if code:
            updates.append((code, row_id))
        else:
            unmapped.append((nombre, sheet))

    if not dry_run and updates:
        cur.executemany(
            "UPDATE raw_eeff_line SET cuenta_codigo_canonical = ? WHERE id = ?",
            updates,
        )
        conn.commit()

    conn.close()

    # Dedup unmapped for reporting
    unmapped_unique = sorted(set(unmapped))
    return {
        "total": len(rows),
        "mapped": len(updates),
        "unmapped": len(rows) - len(updates),
        "unmapped_sample": unmapped_unique[:50],
    }


if __name__ == "__main__":
    import sys
    import json

    db = sys.argv[1] if len(sys.argv) > 1 else "memory/agente_toesca_v2.db"
    dry = "--dry-run" in sys.argv

    print(f"Backfilling {db} {'(dry run)' if dry else ''}...")
    result = backfill_db(db, dry_run=dry)
    print(f"Total: {result['total']}  Mapped: {result['mapped']}  Unmapped: {result['unmapped']}")
    if result["unmapped_sample"]:
        print("\nNo mapeados (muestra):")
        for nombre, sheet in result["unmapped_sample"]:
            print(f"  [{sheet}] {nombre}")
