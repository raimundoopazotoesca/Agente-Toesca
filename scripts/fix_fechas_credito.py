"""
Corrige fechas en dim_credito donde el formato original DD-MM-YYYY
fue ingresado como YYYY-DD-MM en vez de YYYY-MM-DD.
Patrón: '2029-01-11' debería ser '2029-11-01' (1 nov 2029).
Solo aplica cuando el segmento del medio es '01' (día=01 en original).
"""
import sqlite3

DB = 'memory/agente_toesca_v2.db'

def flip_date(d: str) -> str | None:
    """
    Si la fecha almacenada tiene formato YYYY-01-XX (DD fue 01 en original),
    retorna YYYY-XX-01 (formato correcto ISO).
    Si no aplica, retorna None.
    """
    if not d:
        return None
    parts = d.split('-')
    if len(parts) != 3:
        return None
    yyyy, mid, last = parts
    if mid == '01' and 1 <= int(last) <= 12 and last != '01':
        # Original era DD-MM-YYYY con DD=01: '01-XX-YYYY' -> almacenado como YYYY-01-XX
        # Correcto ISO: YYYY-XX-01
        return f"{yyyy}-{last}-01"
    # Si last > 12: la fecha YYYY-01-XX ya es correcta (mes=enero, día=XX)
    return None

con = sqlite3.connect(DB)
cur = con.cursor()

cur.execute("SELECT credito_key, fecha_inicio, fecha_vencimiento FROM dim_credito")
rows = cur.fetchall()

fixes = []
for key, inicio, venc in rows:
    new_venc = flip_date(venc)
    new_inicio = flip_date(inicio)
    if new_venc or new_inicio:
        fixes.append((key, inicio, new_inicio, venc, new_venc))

print("Fechas a corregir:")
for f in fixes:
    key, old_ini, new_ini, old_venc, new_venc = f
    print(f"\n  {key}")
    if new_ini:
        print(f"    inicio: {old_ini}  ->  {new_ini}")
    if new_venc:
        print(f"    venc:   {old_venc}  ->  {new_venc}")

confirm = input("\n¿Aplicar correcciones? (s/n): ").strip().lower()
if confirm == 's':
    for key, old_ini, new_ini, old_venc, new_venc in fixes:
        if new_ini:
            cur.execute("UPDATE dim_credito SET fecha_inicio=? WHERE credito_key=?", (new_ini, key))
        if new_venc:
            cur.execute("UPDATE dim_credito SET fecha_vencimiento=? WHERE credito_key=?", (new_venc, key))
    con.commit()
    print("Correcciones aplicadas.")
else:
    print("Cancelado.")

con.close()
