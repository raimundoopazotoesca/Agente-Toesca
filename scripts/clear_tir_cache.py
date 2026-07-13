import sys
sys.path.insert(0, r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts')
from _common import get_conn

conn = get_conn()

# Borrar todas las entradas de TIR desde inicio cacheadas (pueden estar desactualizadas)
kpis_tir = ['tir_contable_desde_inicio', 'tir_bursatil_desde_inicio']
for kpi in kpis_tir:
    rows = conn.execute(
        "SELECT COUNT(*) FROM derived_kpi WHERE kpi=?", (kpi,)
    ).fetchone()
    print(f"{kpi}: {rows[0]} entradas a borrar")
    conn.execute("DELETE FROM derived_kpi WHERE kpi=?", (kpi,))

conn.commit()
conn.close()
print("Cache limpiado.")
