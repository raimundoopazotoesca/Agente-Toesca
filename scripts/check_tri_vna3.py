import sqlite3, sys
sys.path.insert(0, r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts')

conn = sqlite3.connect(r'C:\Users\raimundo.opazo\automation_agent\memory\agente_toesca_v2.db')

with open(r'C:\Users\raimundo.opazo\automation_agent\scripts\tri_vna_out3.txt', 'w', encoding='utf-8') as f:
    f.write("=== dim_serie columns ===\n")
    rows = conn.execute("PRAGMA table_info(dim_serie)").fetchall()
    for r in rows:
        f.write(str(r) + "\n")

    f.write("\n=== dim_serie rows ===\n")
    rows = conn.execute("SELECT * FROM dim_serie ORDER BY nemotecnico").fetchall()
    for r in rows:
        f.write(str(r) + "\n")

    f.write("\n=== raw_ar_event_line VR CFITOERI1A (last 10) ===\n")
    rows = conn.execute(
        "SELECT fecha, detalle, monto_uf_cuota FROM raw_ar_event_line "
        "WHERE nemotecnico='CFITOERI1A' AND detalle IN ('VR Contable','VR Bursatil') "
        "ORDER BY fecha DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        f.write(str(r) + "\n")

    f.write("\n=== raw_valor_cuota_contable_line CFITOERI1A contable (last 8) ===\n")
    rows = conn.execute(
        "SELECT fecha, tipo, precio_uf FROM raw_valor_cuota_contable_line "
        "WHERE nemotecnico='CFITOERI1A' AND tipo='contable' "
        "ORDER BY fecha DESC LIMIT 8"
    ).fetchall()
    for r in rows:
        f.write(str(r) + "\n")

print("Done")
