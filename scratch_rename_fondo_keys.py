"""
Renombra los fondo_key en la DB y en todo el código fuente.

Mapa:
  'A&R Rentas'    → 'TRI'
  'A&R PT'        → 'PT'
  'A&R Apoquindo' → 'Apo'
"""
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "memory" / "agente_toesca.db"

RENAME = {
    "A&R Rentas":    "TRI",
    "A&R PT":        "PT",
    "A&R Apoquindo": "Apo",
}

# ─── 1. DB ────────────────────────────────────────────────────────────────────
print("=== 1. Renombrando fondo_key en la DB ===")
conn = sqlite3.connect(str(DB_PATH))
conn.execute("PRAGMA foreign_keys = OFF")

for old, new in RENAME.items():
    # Insertar nueva fila en dim_fondo
    conn.execute(
        "INSERT OR IGNORE INTO dim_fondo (fondo_key, nombre, sharepoint_folder) "
        "SELECT ?, nombre, sharepoint_folder FROM dim_fondo WHERE fondo_key = ?",
        (new, old),
    )
    # Actualizar FK en tablas dependientes
    for tabla, col in [
        ("dim_activo",     "fondo_key"),
        ("dim_serie",      "fondo_key"),
        ("raw_eeff_line",  "fondo_key"),
    ]:
        n = conn.execute(
            f"UPDATE {tabla} SET {col} = ? WHERE {col} = ?", (new, old)
        ).rowcount
        if n:
            print(f"  {tabla}.{col}: {old!r} → {new!r} ({n} filas)")
    # derived_kpi: entidad_key cuando entidad_tipo='fondo'
    n = conn.execute(
        "UPDATE derived_kpi SET entidad_key = ? WHERE entidad_tipo = 'fondo' AND entidad_key = ?",
        (new, old),
    ).rowcount
    if n:
        print(f"  derived_kpi.entidad_key: {old!r} → {new!r} ({n} filas)")
    # Borrar fila antigua
    conn.execute("DELETE FROM dim_fondo WHERE fondo_key = ?", (old,))
    print(f"  dim_fondo: {old!r} → {new!r}")

conn.execute("PRAGMA foreign_keys = ON")
conn.commit()

print()
print("dim_fondo final:")
for r in conn.execute("SELECT fondo_key, nombre FROM dim_fondo ORDER BY fondo_key"):
    print(f"  [{r[0]}] {r[1]}")
conn.close()

# ─── 2. Código fuente ─────────────────────────────────────────────────────────
print()
print("=== 2. Reemplazando en archivos fuente ===")

EXTENSIONS = {".py", ".sql", ".md"}

# Excluir archivos que contienen "A&R" solo como referencia a hojas del CDG
# (ej. conceptos/ooxml.md habla de las hojas, no de fondo_key)
EXCLUDE_PATHS = {
    "wiki/conceptos/ooxml.md",
    "wiki/procesos",
    "docs/superpowers",          # planes históricos, no tocar
    "scratch_",                   # scripts temporales
}

def should_skip(path: Path) -> bool:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    return any(ex in rel for ex in EXCLUDE_PATHS)

changed_files = []
for path in ROOT.rglob("*"):
    if path.suffix not in EXTENSIONS:
        continue
    if not path.is_file():
        continue
    if should_skip(path):
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        continue
    new_text = text
    for old, new in RENAME.items():
        new_text = new_text.replace(old, new)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        changed_files.append(str(path.relative_to(ROOT)))
        print(f"  ✓ {path.relative_to(ROOT)}")

if not changed_files:
    print("  (sin cambios)")

print(f"\nTotal: {len(changed_files)} archivos modificados")
