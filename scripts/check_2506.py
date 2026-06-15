import sqlite3
conn = sqlite3.connect('memory/agente_toesca_v2.db')
cur = conn.cursor()
cur.execute("PRAGMA table_info(raw_eeff_line)")
cols = [r[1] for r in cur.fetchall()]
print('Columns:', cols)

cur.execute("SELECT source_sheet, COUNT(*) FROM raw_eeff_line WHERE fondo_key='TRI' AND periodo='2025-06-30' GROUP BY source_sheet")
print('\nTRI 2025-06-30 por source_sheet:')
for r in cur.fetchall():
    print(f'  {r[0]}: {r[1]} cuentas')

cur.execute("SELECT cuenta_nombre, monto_clp FROM raw_eeff_line WHERE fondo_key='TRI' AND periodo='2025-06-30' LIMIT 20")
print('\nPrimeras 20 cuentas:')
for r in cur.fetchall():
    print(f'  {r[0]}: {r[1]}')
conn.close()
