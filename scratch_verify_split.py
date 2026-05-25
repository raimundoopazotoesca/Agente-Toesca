"""Verificación del split PT: consultar_noi por categoria y activo."""
import sys
sys.path.insert(0, ".")

from tools.noi_query import consultar_noi

print("=" * 60)
print("1. consultar_noi('categoria', 'Comercial')")
print("=" * 60)
print(consultar_noi("categoria", "Comercial"))

print()
print("=" * 60)
print("2. consultar_noi('categoria', 'Oficinas')")
print("=" * 60)
print(consultar_noi("categoria", "Oficinas"))

print()
print("=" * 60)
print("3. consultar_noi('activo', 'PT')  — debe ser solo PT real, no duplicar split")
print("=" * 60)
print(consultar_noi("activo", "PT"))

print()
print("=" * 60)
print("4. Verificacion: PT Torre A + PT Boulevard ≈ PT")
print("=" * 60)
from tools.db.connection import get_conn
from tools.noi_query import _noi_activo, _RECIPE, _SPLIT_RECIPE

with get_conn() as conn:
    pt = _noi_activo(conn, "PT", _RECIPE)
    torre_a = _noi_activo(conn, "PT Torre A", _SPLIT_RECIPE)
    boulevard = _noi_activo(conn, "PT Boulevard", _SPLIT_RECIPE)

# Comparar últimos 5 meses
meses = sorted(pt.keys())[-5:]
print(f"{'Periodo':<10} {'PT':>12} {'TorreA+Blvd':>14} {'Diff%':>8}")
print("-" * 50)
for p in meses:
    pt_val = pt.get(p, 0)
    sum_split = torre_a.get(p, 0) + boulevard.get(p, 0)
    if pt_val:
        diff_pct = abs(sum_split - pt_val) / pt_val * 100
        print(f"{p:<10} {pt_val:>12,.1f} {sum_split:>14,.1f} {diff_pct:>7.3f}%")
