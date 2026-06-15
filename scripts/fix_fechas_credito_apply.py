import sqlite3

DB = 'memory/agente_toesca_v2.db'

def flip_date(d):
    if not d:
        return None
    parts = d.split('-')
    if len(parts) != 3:
        return None
    yyyy, mid, last = parts
    if mid == '01' and 1 <= int(last) <= 12 and last != '01':
        return f'{yyyy}-{last}-01'
    return None

con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute('SELECT credito_key, fecha_inicio, fecha_vencimiento FROM dim_credito')
rows = cur.fetchall()

applied = 0
for key, inicio, venc in rows:
    new_inicio = flip_date(inicio)
    new_venc = flip_date(venc)
    if new_inicio:
        cur.execute('UPDATE dim_credito SET fecha_inicio=? WHERE credito_key=?', (new_inicio, key))
        applied += 1
    if new_venc:
        cur.execute('UPDATE dim_credito SET fecha_vencimiento=? WHERE credito_key=?', (new_venc, key))
        applied += 1

con.commit()
con.close()
print(f'Aplicadas {applied} correcciones.')

# Verificar PT
con2 = sqlite3.connect(DB)
cur2 = con2.cursor()
cur2.execute("SELECT credito_key, fecha_inicio, fecha_vencimiento FROM dim_credito WHERE fondo_key='PT'")
print('\nPT fechas post-fix:')
for r in cur2.fetchall(): print(r)
con2.close()
