import sqlite3

DB = 'memory/agente_toesca_v2.db'
con = sqlite3.connect(DB)
cur = con.cursor()

# Muestra raw_eeff_line PT 2018-12-31
cur.execute("""
    SELECT cuenta_codigo, cuenta_nombre, monto_clp, monto_uf
    FROM raw_eeff_line
    WHERE fondo_key='PT' AND periodo='2018-12-31'
    ORDER BY id
""")
rows = cur.fetchall()
print(f'PT 2018-12-31 ({len(rows)} filas):')
for r in rows:
    print(r)

con.close()
