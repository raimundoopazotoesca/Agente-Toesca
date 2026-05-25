"""
Limpia proyecciones contaminadas y re-corre backfill NOI con fix definitivo.
"""
from tools.db.connection import get_conn

# 1. Borrar todos los registros NOI posteriores a Feb-2026 (proyecciones)
conn = get_conn()
print("=== Limpiando proyecciones (> 2026-02) ===")
rows = conn.execute(
    "SELECT entidad_key, periodo, valor FROM derived_kpi "
    "WHERE kpi='noi_mensual' AND recipe='cdg_noi_real_v1' AND periodo > '2026-02' "
    "ORDER BY entidad_key, periodo"
).fetchall()
for r in rows:
    print(f"  BORRANDO: {r[0]} {r[1]} = {r[2]:.1f}")

deleted = conn.execute(
    "DELETE FROM derived_kpi WHERE kpi='noi_mensual' AND recipe='cdg_noi_real_v1' AND periodo > '2026-02'"
).rowcount
conn.commit()
conn.close()
print(f"  -> {deleted} registros eliminados\n")

# 2. Re-correr backfill NOI con la nueva deteccion por fila PT
print("=== Re-corriendo backfill NOI (deteccion por fila PT) ===")
from tools.db.backfill import backfill_noi
rep = backfill_noi(verbose=True)
print(f"\nTotal: {rep['filas']} valores")
if rep["sin_datos"]:
    for s in rep["sin_datos"]:
        print(f"  AVISO: {s}")

# 3. Verificar: no debe haber datos > 2026-02 para cdg_noi_real_v1
print("\n=== Verificacion: max periodo por activo ===")
conn2 = get_conn()
rows2 = conn2.execute(
    "SELECT entidad_key, recipe, COUNT(*) as n, MIN(periodo) as desde, MAX(periodo) as hasta "
    "FROM derived_kpi WHERE kpi='noi_mensual' GROUP BY entidad_key, recipe ORDER BY entidad_key"
).fetchall()
for r in rows2:
    flag = " <-- REVISAR" if r["hasta"] > "2026-02" and r["recipe"] == "cdg_noi_real_v1" else ""
    print(f"  {r['entidad_key']} | {r['n']} meses | {r['desde']}..{r['hasta']}{flag}")
conn2.close()
