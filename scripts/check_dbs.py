import sqlite3, os

for db in ['memory/agente_toesca.db', 'memory/agente_toesca_v2.db']:
    if os.path.exists(db):
        size = os.path.getsize(db)
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        print(f"{db} ({size/1024/1024:.1f}MB): {tables}")
        con.close()
    else:
        print(f"{db}: NOT FOUND")
