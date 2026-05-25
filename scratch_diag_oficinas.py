"""Diagnosticar el NOI negativo en categoría Oficinas para 2026-04 y 2026-05."""
from tools.db.connection import get_conn
from tools.noi_query import _noi_activo, _RECIPE, _SPLIT_RECIPE, _CATEGORIA_FUENTE, _SPLIT_PART

with get_conn() as conn:
    print("=== Fuentes de categoría 'Oficinas' ===")
    for entidad, recipe in _CATEGORIA_FUENTE["Oficinas"]:
        serie = _noi_activo(conn, entidad, recipe)
        ultimos = {p: v for p, v in serie.items() if p >= "2026-01"}
        print(f"  {entidad} (recipe={recipe}):")
        for p, v in sorted(ultimos.items()):
            print(f"    {p}: {v:,.1f}")
