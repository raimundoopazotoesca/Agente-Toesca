import sqlite3

DB = 'memory/agente_toesca_v2.db'
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("PRAGMA table_info(raw_pagare_intercompania)")
cols = [c[1] for c in cur.fetchall()]
print("Cols:", cols)
cur.execute("SELECT * FROM raw_pagare_intercompania")
for r in cur.fetchall(): print(dict(zip(cols, r)))
con.close()
