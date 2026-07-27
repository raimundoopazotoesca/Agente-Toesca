"""Recalcula todos los KPIs derivados dependientes de raw_er_activo_line /
raw_valor_cuota_bursatil que tienen un consolidador vivo (script recurrente,
no backfill de una sola vez).

Se corre automáticamente después de cada ingesta (ver
scripts/ingesta_server.py:_rebuild_factsheet) para que ningún derived_kpi
quede congelado en un período viejo cuando entra data nueva — bug detectado
2026-07-27: ingresos_mes/noi_mes/tasa_arriendo/cap_rate de TRI quedaron
pegados en 2026-03 durante meses porque nadie volvió a correr los scripts
consolidate_* tras ingestar EEFF/NOI nuevos.

Orden de dependencias (no reordenar sin revisar):
  1. consolidate_ingresos_tri  — ingresos_mes/ingresos_u12m fondo TRI
  2. consolidate_noi_tri       — noi_mes/noi_u12m fondo TRI
  3. consolidate_kpis_bursatil_tri — tasa_arriendo/cap_rate por serie TRI
     (depende de ingresos_u12m/noi_u12m de (1) y (2))
  4. consolidate_kpis_bursatil_pt  — tasa_arriendo/cap_rate fondo PT
     (depende de ingresos_u12m/noi_u12m fondo PT — ver nota abajo)

GAP CONOCIDO: ingresos_mes/noi_mes/ingresos_u12m/noi_u12m a nivel fondo PT
y Apo (usados por (4) y por el factsheet de esos fondos) no tienen un
consolidador recurrente — se persistieron una sola vez en un backfill
(migración 049, commit cdc8a03) y se congelarán en el último período de ese
backfill en cuanto haya EEFF nuevos de Torre A/Boulevard/Apo4501/Apo4700.
Falta escribir consolidate_ingresos_noi_pt.py / _apo.py análogos a los de
TRI. No se resuelve aquí — requiere validar la metodología con el usuario
igual que se hizo para TRI.
"""
from __future__ import annotations

import importlib


_PASOS = [
    "scripts.consolidate_ingresos_tri",
    "scripts.consolidate_noi_tri",
    "scripts.consolidate_kpis_bursatil_tri",
    "scripts.consolidate_kpis_bursatil_pt",
]


def main() -> None:
    for modulo in _PASOS:
        print(f"--- {modulo} ---")
        mod = importlib.import_module(modulo)
        mod.main()


if __name__ == "__main__":
    main()
