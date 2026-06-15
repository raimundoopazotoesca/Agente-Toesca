import sqlite3
from datetime import date

DB = 'memory/agente_toesca_v2.db'
con = sqlite3.connect(DB)
cur = con.cursor()

# fact_adquisicion
print("=== fact_adquisicion PT ===")
cur.execute("SELECT * FROM fact_adquisicion WHERE activo_key IN ('Torre A','Boulevard','PT')")
cur2 = con.cursor()
cur2.execute("PRAGMA table_info(fact_adquisicion)")
cols2 = [c[1] for c in cur2.fetchall()]
print("Cols:", cols2)
for r in cur.fetchall(): print(dict(zip(cols2, r)))

# Summary PT 2025 (latest tasacion, Promedio)
print("\n=== PT Consolidado (Promedio, 2025) ===")
cur.execute("""
    SELECT activo_key, tasador, valor_uf, ltv, ltc, leverage_fin, tasa_dcto
    FROM fact_tasacion
    WHERE activo_key IN ('Torre A','Boulevard')
      AND periodo = '2025'
      AND tasador IN ('Promedio','Colliers','Transsa')
    ORDER BY activo_key, tasador
""")
for r in cur.fetchall(): print(r)

# Deuda y tasas 2026-06
print("\n=== Deuda PT jun-2026 (para tasa promedio y duration) ===")
cur.execute("""
    SELECT c.credito_key, c.activo_key, c.acreedor, c.tasa_anual,
           c.fecha_vencimiento, c.perfil_amortizacion,
           d.saldo_uf
    FROM raw_deuda_saldo_line d
    JOIN dim_credito c ON c.credito_key = d.credito_key
    WHERE c.fondo_key = 'PT' AND d.periodo = '2026-06'
""")
rows = cur.fetchall()
for r in rows: print(r)

# Compute tasa promedio ponderada
total_saldo = sum(r[6] for r in rows)
tasa_pond = sum(r[3] * r[6] for r in rows) / total_saldo if total_saldo else 0
print(f"\nTasa promedio ponderada: {tasa_pond*100:.2f}%")
print(f"Total saldo: UF {total_saldo:,.0f}")

# Duration (años hasta vencimiento, bullet ≈ duration)
today = date(2026, 6, 11)
print("\nDuration por crédito:")
for r in rows:
    venc = date.fromisoformat(r[4])
    years = (venc - today).days / 365.25
    print(f"  {r[0]}: vence {r[4]}, {years:.2f} años, tasa {r[3]*100:.2f}%, saldo UF {r[6]:,.0f}")

con.close()
