import sqlite3

DB = 'memory/agente_toesca_v2.db'
con = sqlite3.connect(DB)
cur = con.cursor()

# What's in raw_eeff_line for PT?
print("=== raw_eeff_line PT periodos disponibles ===")
cur.execute("""
    SELECT periodo, COUNT(*) as n_cuentas
    FROM raw_eeff_line
    WHERE fondo_key = 'PT' AND superseded_at IS NULL
    GROUP BY periodo ORDER BY periodo DESC LIMIT 10
""")
for r in cur.fetchall(): print(r)

# raw_valor_cuota_contable_line for PT - latest
print("\n=== raw_valor_cuota_contable_line PT latest ===")
cur.execute("""
    SELECT nemotecnico, fecha, tipo, precio_clp, precio_uf, cuotas, periodo
    FROM raw_valor_cuota_contable_line
    WHERE fondo_key = 'PT' AND superseded_at IS NULL
    ORDER BY fecha DESC LIMIT 10
""")
for r in cur.fetchall(): print(r)

# raw_cuota_en_circulacion_line for PT
print("\n=== raw_cuota_en_circulacion_line PT ===")
cur.execute("PRAGMA table_info(raw_cuota_en_circulacion_line)")
cols = [c[1] for c in cur.fetchall()]
print("Cols:", cols)
cur.execute("""
    SELECT * FROM raw_cuota_en_circulacion_line
    WHERE fondo_key = 'PT'
    ORDER BY periodo DESC LIMIT 10
""")
for r in cur.fetchall(): print(dict(zip(cols, r)))

# Patrimonio bursátil PT (ahora vive en raw_valor_cuota_bursatil_line)
print("\n=== raw_valor_cuota_bursatil_line PT (patrimonio) ===")
cur.execute("""
    SELECT nemotecnico, fecha, precio_uf, n_cuotas, patrimonio_bursatil_uf, fuente
    FROM raw_valor_cuota_bursatil_line
    WHERE nemotecnico = 'CFITRIPT-E' AND patrimonio_bursatil_uf IS NOT NULL
    ORDER BY fecha DESC LIMIT 10
""")
for r in cur.fetchall(): print(r)

con.close()
