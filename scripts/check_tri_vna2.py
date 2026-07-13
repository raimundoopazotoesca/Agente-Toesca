import sqlite3

conn = sqlite3.connect(r'C:\Users\raimundo.opazo\automation_agent\memory\agente_toesca_v2.db')

with open(r'C:\Users\raimundo.opazo\automation_agent\scripts\tri_vna_out2.txt', 'w', encoding='utf-8') as f:
    # Contar filas en las tablas clave
    for t in ['raw_ar_event_line', 'raw_valor_cuota_contable_line', 'raw_dividendo_line']:
        row = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
        f.write(f"{t}: {row[0]} rows\n")

    f.write("\n=== raw_ar_event_line sample (10 rows) ===\n")
    rows = conn.execute("SELECT nemotecnico, fecha, detalle, monto_uf_cuota FROM raw_ar_event_line LIMIT 10").fetchall()
    for r in rows:
        f.write(str(r) + "\n")

    f.write("\n=== raw_ar_event_line nemotecnicos distintos ===\n")
    rows = conn.execute("SELECT DISTINCT nemotecnico FROM raw_ar_event_line ORDER BY nemotecnico").fetchall()
    for r in rows:
        f.write(str(r) + "\n")

    f.write("\n=== raw_valor_cuota_contable_line nemotecnicos distintos ===\n")
    rows = conn.execute("SELECT DISTINCT nemotecnico FROM raw_valor_cuota_contable_line ORDER BY nemotecnico").fetchall()
    for r in rows:
        f.write(str(r) + "\n")

    f.write("\n=== TIR skill DB path ===\n")
    # Verificar el path que usa el skill
    import sys
    sys.path.insert(0, r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts')
    try:
        from _common import get_conn
        c2 = get_conn()
        row = c2.execute("SELECT COUNT(*) FROM raw_ar_event_line").fetchone()
        f.write(f"skill DB raw_ar_event_line: {row[0]} rows\n")
        rows = c2.execute("SELECT DISTINCT nemotecnico FROM raw_ar_event_line ORDER BY nemotecnico").fetchall()
        for r in rows:
            f.write(str(r) + "\n")
    except Exception as e:
        f.write(f"Error loading skill: {e}\n")

print("Done")
