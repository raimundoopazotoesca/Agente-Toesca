from tools.db.connection import get_conn
conn = get_conn()

print("=== Vacancia Curicó - Marzo 2026 ===")
rows = conn.execute(
    "SELECT entidad_key, periodo, kpi, valor, unidad FROM derived_kpi "
    "WHERE kpi='m2_vacantes' AND entidad_key LIKE '%uric%' AND periodo='2026-03' "
    "ORDER BY entidad_key"
).fetchall()

if rows:
    for r in rows:
        print(f"  {r[0]} | {r[1]} | {r[3]:,.1f} {r[4]}")
else:
    print("  (sin dato para 2026-03 en la DB)")
    rows2 = conn.execute(
        "SELECT entidad_key, periodo, kpi, valor, unidad FROM derived_kpi "
        "WHERE kpi='m2_vacantes' AND entidad_key LIKE '%uric%' "
        "ORDER BY periodo DESC LIMIT 3"
    ).fetchall()
    print("  Últimos datos disponibles:")
    for r in rows2:
        print(f"  {r[0]} | {r[1]} | {r[3]:,.1f} {r[4]}")

conn.close()
