import sqlite3

con = sqlite3.connect('memory/agente_toesca.db')
cur = con.cursor()

# All tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

# Check for financing/debt related tables
for t in tables:
    if any(k in t.lower() for k in ['financ', 'debt', 'deuda', 'prestamo', 'credito', 'capital', 'amort']):
        print(f"\n--- {t} ---")
        cur.execute(f"SELECT * FROM {t} LIMIT 3")
        rows = cur.fetchall()
        cur.execute(f"PRAGMA table_info({t})")
        cols = [c[1] for c in cur.fetchall()]
        print("Cols:", cols)
        for r in rows:
            print(r)

# Also check raw_eeff_line for PT debt accounts
print("\n--- raw_eeff_line cuentas PT (pasivos/deuda) ---")
cur.execute("""
    SELECT cuenta_codigo, cuenta_nombre, periodo, SUM(monto_uf) as monto_uf, SUM(monto_clp) as monto_clp
    FROM raw_eeff_line
    WHERE fondo_key = 'PT'
      AND superseded_at IS NULL
      AND (LOWER(cuenta_nombre) LIKE '%deuda%'
           OR LOWER(cuenta_nombre) LIKE '%prestamo%'
           OR LOWER(cuenta_nombre) LIKE '%credito%'
           OR LOWER(cuenta_nombre) LIKE '%financ%'
           OR LOWER(cuenta_nombre) LIKE '%obligacion%'
           OR LOWER(cuenta_nombre) LIKE '%pasivo%')
    GROUP BY cuenta_codigo, cuenta_nombre, periodo
    ORDER BY periodo DESC
    LIMIT 40
""")
rows = cur.fetchall()
for r in rows:
    print(r)

con.close()
