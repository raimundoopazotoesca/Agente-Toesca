"""Captura serie NOI ponderada de PT y Apo antes de migración 049.
Se usa como baseline anti-regresión: post-049, el mismo script debe
devolver los mismos números (la columna vieja participacion_fondo_activo
no se toca, entonces noi_query sigue leyendo los mismos valores).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.db.connection import get_conn_for
from tools import noi_query


# entidad_key agregado por fondo en derived_kpi (no coincide con
# dim_activo.activo_key — nivel="fondo" de noi_query no resuelve estos
# fondos, por eso se consulta directo por el entidad_key agregado).
_ENTIDAD_POR_FONDO = {"PT": "PT", "Apo": "Apoquindo"}


def capture(db_path: str) -> dict:
    conn = get_conn_for(db_path)
    out = {}
    for fondo, entidad_key in _ENTIDAD_POR_FONDO.items():
        serie = noi_query.serie_mensual(conn, nivel="activo", clave=entidad_key, ponderado=True)
        out[fondo] = {p: round(v, 6) for p, v in serie.items()}
    return out


if __name__ == "__main__":
    db = "memory/agente_toesca_v2.db"
    out_path = "scratchpad/noi_snapshot_pre_049.json"
    Path("scratchpad").mkdir(exist_ok=True)
    snap = capture(db)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, sort_keys=True)
    print(f"OK: {out_path} — PT={len(snap['PT'])} periodos, Apo={len(snap['Apo'])} periodos")
