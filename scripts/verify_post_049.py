# scripts/verify_post_049.py
"""Compara snapshot post-migración con baseline pre-049 (Task 1).
Debe ser idéntico: participacion_fondo_activo no se tocó, entonces
noi_query devuelve los mismos números.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.snapshot_pre_049 import capture


def main():
    baseline = json.load(open("scratchpad/noi_snapshot_pre_049.json"))
    now = capture("memory/agente_toesca_v2.db")

    ok = True
    for fondo in ("PT", "Apo"):
        b, n = baseline[fondo], now[fondo]
        if set(b.keys()) != set(n.keys()):
            print(f"FAIL {fondo}: distintos periodos. Baseline={len(b)}, ahora={len(n)}")
            ok = False
            continue
        for periodo, v_base in b.items():
            v_now = round(n[periodo], 6)
            if abs(v_base - v_now) > 1e-6:
                print(f"FAIL {fondo} {periodo}: baseline={v_base} vs ahora={v_now}")
                ok = False
    if ok:
        print("OK: noi_query.serie_mensual(ponderado=True) idéntico pre vs post 049")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
