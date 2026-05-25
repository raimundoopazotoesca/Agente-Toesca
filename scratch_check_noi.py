"""Aplica los nombres oficiales de fondos y verifica la estructura completa."""
from tools.db.connection import get_conn

conn = get_conn()
conn.execute("UPDATE dim_fondo SET nombre='Fondo Toesca Rentas Inmobiliarias PT' WHERE fondo_key='A&R PT'")
conn.execute("UPDATE dim_fondo SET nombre='Fondo Toesca Rentas Inmob Apoquindo' WHERE fondo_key='A&R Apoquindo'")
conn.commit()

print("=== Estructura de fondos (oficial) ===")
for r in conn.execute("SELECT fondo_key, nombre FROM dim_fondo ORDER BY fondo_key"):
    print(f"  [{r[0]}] {r[1]}")

print()
print("=== Activos por fondo ===")
for r in conn.execute(
    "SELECT f.nombre as fondo, a.activo_key, a.participacion, a.categoria "
    "FROM dim_activo a JOIN dim_fondo f ON a.fondo_key = f.fondo_key "
    "ORDER BY f.fondo_key, a.activo_key"
):
    print(f"  {r['fondo']:<45} | {r['activo_key']:<14} | {r['participacion']} | {r['categoria']}")

conn.close()
