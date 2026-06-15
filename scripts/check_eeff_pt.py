import sqlite3

DB = 'memory/agente_toesca_v2.db'
con = sqlite3.connect(DB)
cur = con.cursor()

# What's in raw_eeff_line for PT at all?
print("=== raw_eeff_line PT - todos los registros ===")
cur.execute("""
    SELECT fondo_key, periodo, COUNT(*) as n
    FROM raw_eeff_line
    WHERE fondo_key = 'PT'
    GROUP BY fondo_key, periodo
    ORDER BY periodo DESC
""")
rows = cur.fetchall()
print(f"Total periodos: {len(rows)}")
for r in rows: print(r)

# Maybe all funds?
print("\n=== raw_eeff_line - fondos disponibles ===")
cur.execute("""
    SELECT fondo_key, COUNT(DISTINCT periodo) as periodos, COUNT(*) as n
    FROM raw_eeff_line
    GROUP BY fondo_key
""")
for r in cur.fetchall(): print(r)

# Latest PT period with any data
print("\n=== raw_eeff_line PT latest (ignoring superseded) ===")
cur.execute("""
    SELECT periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf, superseded_at
    FROM raw_eeff_line
    WHERE fondo_key = 'PT'
    ORDER BY periodo DESC
    LIMIT 20
""")
for r in cur.fetchall(): print(r)

con.close()
