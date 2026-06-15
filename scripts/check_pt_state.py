import sqlite3

DB = 'memory/agente_toesca_v2.db'
con = sqlite3.connect(DB)
cur = con.cursor()

# Schema
cur.execute('PRAGMA table_info(raw_eeff_line)')
print('raw_eeff_line cols:', [c[1] for c in cur.fetchall()])
cur.execute('PRAGMA table_info(raw_valor_cuota_line)')
print('raw_valor_cuota_line cols:', [c[1] for c in cur.fetchall()])

# raw_valor_cuota_line PT
cur.execute("SELECT fecha, precio_clp, source_file FROM raw_valor_cuota_line WHERE fondo_key='PT' ORDER BY fecha")
rows = cur.fetchall()
print(f'\nraw_valor_cuota_line PT: {len(rows)} registros')
for r in rows: print(' ', r)

# raw_cuota_en_circulacion_line PT
cur.execute("SELECT fecha, cuotas, source_file FROM raw_cuota_en_circulacion_line WHERE fondo_key='PT' ORDER BY fecha")
rows2 = cur.fetchall()
print(f'\nraw_cuota_en_circulacion_line PT: {len(rows2)} registros')
for r in rows2: print(' ', r)

con.close()
