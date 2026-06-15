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

# raw_valor_cuota_line for PT - latest
print("\n=== raw_valor_cuota_line PT latest ===")
cur.execute("""
    SELECT nemotecnico, fecha, tipo, precio_clp, precio_uf, cuotas, periodo
    FROM raw_valor_cuota_line
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

# raw_patrimonio_bursatil_line for PT
print("\n=== raw_patrimonio_bursatil_line PT ===")
cur.execute("PRAGMA table_info(raw_patrimonio_bursatil_line)")
cols3 = [c[1] for c in cur.fetchall()]
print("Cols:", cols3)
cur.execute("""
    SELECT * FROM raw_patrimonio_bursatil_line
    WHERE fondo_key = 'PT'
    ORDER BY periodo DESC LIMIT 10
""")
for r in cur.fetchall(): print(dict(zip(cols3, r)))

con.close()
