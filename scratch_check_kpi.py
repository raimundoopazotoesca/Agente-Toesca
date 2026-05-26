from tools.db.connection import get_conn
conn = get_conn()

print("=== KPIs Curicó - Febrero 2026 ===")
rows = conn.execute(
    "SELECT kpi, valor, unidad FROM derived_kpi "
    "WHERE (entidad_key LIKE '%uric%' OR entidad_key = 'Mall Curicó') AND periodo='2026-02' "
    "ORDER BY kpi"
).fetchall()

for r in rows:
    print(f"  {r[0]} | {r[1]:,.2f} {r[2]}")

print("\n=== Todos los KPIs disponibles para Curicó ===")
rows2 = conn.execute(
    "SELECT DISTINCT kpi FROM derived_kpi "
    "WHERE (entidad_key LIKE '%uric%' OR entidad_key = 'Mall Curicó') "
    "ORDER BY kpi"
).fetchall()
for r in rows2:
    print(f"  {r[0]}")

conn.close()
