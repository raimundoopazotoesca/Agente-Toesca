import sqlite3

conn = sqlite3.connect(r'C:\Users\raimundo.opazo\automation_agent\memory\agente_toesca_v2.db')

with open(r'C:\Users\raimundo.opazo\automation_agent\scripts\tri_vna_out.txt', 'w', encoding='utf-8') as f:
    f.write("=== raw_ar_event_line VR para TRI ===\n")
    rows = conn.execute(
        "SELECT nemotecnico, fecha, detalle, monto_uf_cuota "
        "FROM raw_ar_event_line "
        "WHERE nemotecnico LIKE 'TRI%' AND detalle IN ('VR Contable','VR Bursatil') "
        "ORDER BY fecha DESC LIMIT 20"
    ).fetchall()
    for r in rows:
        f.write(str(r) + "\n")

    f.write("\n=== raw_valor_cuota_contable_line TRI-1A contable (ultimos 8) ===\n")
    rows2 = conn.execute(
        "SELECT fecha, tipo, precio_uf FROM raw_valor_cuota_contable_line "
        "WHERE nemotecnico='TRI-1A' AND tipo='contable' "
        "ORDER BY fecha DESC LIMIT 8"
    ).fetchall()
    for r in rows2:
        f.write(str(r) + "\n")

    f.write("\n=== Tablas disponibles ===\n")
    rows3 = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for r in rows3:
        f.write(str(r) + "\n")

print("Done")
