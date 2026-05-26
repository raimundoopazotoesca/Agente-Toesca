#!/usr/bin/env python
"""
Extrae valores cuota contables (col I, filtrado por col E='Contable')
y dividendos (col J approx) desde hojas A&R del CDG.
"""
import pandas as pd
import sqlite3
from pathlib import Path
import hashlib

CDG_PATH = Path("work/eeff_ingesta/TRI/cdg_extract.xlsx")
DB_PATH = Path("memory/agente_toesca.db")

AR_SHEETS = {
    "A&R Rentas": "TRI",
    "A&R PT": "PT",
    "A&R Apoquindo": "Apo",
}

def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def extract_from_ar_sheet(file_path: Path, sheet_name: str, fondo_key: str):
    """Extrae VC contables (col I, filtro col E) y dividendos desde hoja A&R"""
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl", header=None)
        print(f"  Shape: {df.shape}")
        print(f"  Primeras columnas: {df.iloc[0, :10].tolist()}")

        vc_rows = []
        div_rows = []

        # Asumo: fila 0 = headers, datos desde fila 1
        # Col E (idx 4) = tipo, Col I (idx 8) = valor cuota, Col J (idx 9) = dividendo?
        for idx in range(1, len(df)):
            col_a = df.iloc[idx, 0]  # Fecha
            col_e = df.iloc[idx, 4] if len(df.columns) > 4 else None  # Tipo (Contable/Bursátil)
            col_i = df.iloc[idx, 8] if len(df.columns) > 8 else None  # Valor cuota
            col_j = df.iloc[idx, 9] if len(df.columns) > 9 else None  # Dividendo (?)

            # Valor cuota contable
            if col_e and col_i and "Contable" in str(col_e):
                if pd.notna(col_i):
                    vc_rows.append({
                        "fondo_key": fondo_key,
                        "periodo": str(col_a).split()[0] if pd.notna(col_a) else None,
                        "valor_cuota": float(col_i) if isinstance(col_i, (int, float)) else None,
                        "tipo": str(col_e),
                        "source": sheet_name,
                        "row": idx + 1,
                    })

            # Dividendo (si existe en col J y no es vacío)
            if pd.notna(col_j) and col_j != "" and col_j != 0:
                # Mapear nemotécnico según fondo
                nemo_map = {"TRI": "CFITRIPT-E", "PT": "CFITRIPT-C", "Apo": "CFITRIPT-I"}
                div_rows.append({
                    "nemotecnico": nemo_map.get(fondo_key, f"CFITRI{fondo_key[0]}"),
                    "fecha_pago": str(col_a).split()[0] if pd.notna(col_a) else None,
                    "monto": float(col_j) if isinstance(col_j, (int, float)) else None,
                    "source": sheet_name,
                })

        return vc_rows, div_rows

    except Exception as e:
        print(f"  ERROR: {e}")
        return [], []

# Main
if not CDG_PATH.exists():
    print(f"ERROR: {CDG_PATH} no existe")
    exit(1)

print(f"Abriendo: {CDG_PATH.name}")

all_vc = []
all_div = []

for sheet_name, fondo_key in AR_SHEETS.items():
    print(f"\n{sheet_name} ({fondo_key})...")
    vc, div = extract_from_ar_sheet(CDG_PATH, sheet_name, fondo_key)
    print(f"  >> {len(vc)} VC, {len(div)} dividendos")
    all_vc.extend(vc)
    all_div.extend(div)

print("\n=== Resumen ===")
print("Total VC: " + str(len(all_vc)))
print("Total dividendos: " + str(len(all_div)))

if all_vc:
    print("\nMuestra VC (primeros 3):")
    for r in all_vc[:3]:
        print("  " + r['fondo_key'] + " " + str(r['periodo']) + ": " + str(r['valor_cuota']))

if all_div:
    print("\nMuestra dividendos (primeros 3):")
    for r in all_div[:3]:
        print("  " + r['nemotecnico'] + " " + str(r['fecha_pago']) + ": " + str(r['monto']))

print(f"\n=== Persistencia ===")
con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# VC → fact_valor_cuota (crear tabla si no existe)
if all_vc:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fact_valor_cuota (
            id INTEGER PRIMARY KEY,
            fondo_key TEXT NOT NULL,
            periodo TEXT NOT NULL,
            valor_contable REAL,
            loaded_at TEXT DEFAULT (datetime('now')),
            source_file TEXT,
            source_row INTEGER,
            file_hash TEXT
        )
    """)

    fhash = file_hash(CDG_PATH)
    n = 0
    for r in all_vc:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO fact_valor_cuota
                (fondo_key, periodo, valor_contable, source_file, source_row, file_hash)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (r["fondo_key"], r["periodo"], r["valor_cuota"], r["source"], r["row"], fhash))
            n += 1
        except Exception as e:
            print(f"  error insert VC: {e}")
    con.commit()
    print("[OK] fact_valor_cuota: " + str(n) + " inserts")

# Dividendos → fact_dividendo
if all_div:
    n = 0
    for r in all_div:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO fact_dividendo
                (nemotecnico, fecha_pago, monto)
                VALUES (?, ?, ?)
            """, (r["nemotecnico"], r["fecha_pago"], r["monto"]))
            n += 1
        except Exception as e:
            print("  error insert div: " + str(e))
    con.commit()
    print("[OK] fact_dividendo: " + str(n) + " inserts")

con.close()
print("\n[DONE]")
