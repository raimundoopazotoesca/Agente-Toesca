import sqlite3

con = sqlite3.connect('memory/agente_toesca_v2.db')
cur = con.cursor()

# Ver duplicados 2019-12-31 por source_file
cur.execute("""
    SELECT source_file, COUNT(*) FROM raw_eeff_line
    WHERE fondo_key='PT' AND periodo='2019-12-31'
    GROUP BY source_file
""")
print("2019-12-31 por source_file:")
for r in cur.fetchall(): print(' ', r)

# Borrar las filas con source_file='2020-03-31.json' (duplicado del comparativo)
cur.execute("""
    DELETE FROM raw_eeff_line
    WHERE fondo_key='PT' AND periodo='2019-12-31' AND source_file='2020-03-31.json'
""")
print(f"\nEliminadas: {cur.rowcount} filas duplicadas de 2019-12-31")

# Verificar
cur.execute("""
    SELECT source_file, COUNT(*) FROM raw_eeff_line
    WHERE fondo_key='PT' AND periodo='2019-12-31'
    GROUP BY source_file
""")
print("Después:")
for r in cur.fetchall(): print(' ', r)

con.commit()
con.close()
