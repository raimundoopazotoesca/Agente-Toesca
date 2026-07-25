"""Congela el estado actual de `derived_kpi` como baseline de regresión.

Motivación: la skill `real-estate-finance-expert` no está disponible en esta
máquina (ROADMAP F0.6, bloqueado por acceso al computador Windows). Sus 15 KPIs
—6.246 filas— no se pueden recalcular hoy. Antes de tocar nada, se congela lo que
hay: cuando la skill se recupere o se reimplemente, cada KPI debe **reproducir**
este golden antes de reemplazar los valores históricos.

Es trabajo útil pase lo que pase: sirve tanto si el código aparece (para auditar
lo que se incorpora) como si hay que reescribirlo desde el wiki.

Uso:
    python scripts/congelar_golden_kpis.py                 # genera el golden
    python scripts/congelar_golden_kpis.py --verificar     # compara contra él
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db.connection import DEFAULT_DB_PATH, get_conn_for  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "derived_kpi_golden.json"

# KPIs que produce la skill financiera. Los demás (noi_*, ingresos_*) se calculan
# con scripts que sí están en el repo.
KPIS_SKILL = (
    "dy", "dy_amort",
    "ltv", "ltc", "dscr", "duration_deuda", "perfil_vencimiento", "leverage_financiero",
    "tir_bursatil_desde_inicio", "tir_contable_desde_inicio",
    "tir_bursatil_u12m", "tir_contable_u12m", "tir_contable_ytd",
    "rent_ytd_bursatil", "rent_ytd_contable",
)

# Tolerancias de regresión por familia de KPI. Una reimplementación se considera
# correcta si reproduce el golden dentro de estos márgenes.
#   Las TIR y rentabilidades son tasas: se comparan en puntos porcentuales.
#   Los ratios (ltv, leverage) también.
#   duration_deuda está en años; perfil_vencimiento en monto.
TOLERANCIAS = {
    "tir": 1e-6,          # 0,0001 pp — XIRR por bisección debe converger igual
    "rent": 1e-6,
    "dy": 1e-6,
    "ratio": 1e-6,        # ltv, ltc, dscr, leverage_financiero
    "duration": 1e-4,     # años
    "monto": 0.01,        # perfil_vencimiento, en la unidad que traiga
}


def _familia(kpi: str) -> str:
    if kpi.startswith("tir"):
        return "tir"
    if kpi.startswith("rent"):
        return "rent"
    if kpi.startswith("dy"):
        return "dy"
    if kpi == "duration_deuda":
        return "duration"
    if kpi == "perfil_vencimiento":
        return "monto"
    return "ratio"


def _clave(fila) -> str:
    return "|".join(str(x) for x in (
        fila["kpi"], fila["entidad_tipo"], fila["entidad_key"],
        fila["periodo"], fila["variante"] or "", fila["formula"] or "",
    ))


def _leer(con) -> dict:
    marks = ",".join("?" * len(KPIS_SKILL))
    filas = con.execute(
        f"""SELECT kpi, entidad_tipo, entidad_key, periodo, variante, formula, valor, unidad
              FROM derived_kpi WHERE kpi IN ({marks})
             ORDER BY kpi, entidad_tipo, entidad_key, periodo""",
        KPIS_SKILL,
    ).fetchall()
    return {_clave(f): {"valor": f["valor"], "unidad": f["unidad"]} for f in filas}


def generar(con) -> int:
    datos = _leer(con)
    resumen: dict[str, int] = {}
    for clave in datos:
        resumen[clave.split("|", 1)[0]] = resumen.get(clave.split("|", 1)[0], 0) + 1

    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(
        json.dumps(
            {
                "_nota": (
                    "Golden de regresión de los KPIs que produce la skill "
                    "real-estate-finance-expert. Generado por "
                    "scripts/congelar_golden_kpis.py. Ninguna reimplementación "
                    "debe reemplazar valores históricos sin reproducir esto."
                ),
                "_tolerancias": TOLERANCIAS,
                "_filas_por_kpi": resumen,
                "valores": datos,
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"Golden congelado: {len(datos):,} valores en {GOLDEN.relative_to(ROOT)}")
    for kpi, n in sorted(resumen.items(), key=lambda x: -x[1]):
        print(f"  {kpi:30} {n:>6,}")
    return 0


def verificar(con) -> int:
    if not GOLDEN.exists():
        print("No existe el golden. Genéralo primero.", file=sys.stderr)
        return 1
    esperado = json.loads(GOLDEN.read_text(encoding="utf-8"))["valores"]
    actual = _leer(con)

    faltan = sorted(set(esperado) - set(actual))
    nuevos = sorted(set(actual) - set(esperado))
    difieren = []
    for clave in set(esperado) & set(actual):
        a, b = esperado[clave]["valor"], actual[clave]["valor"]
        if a is None or b is None:
            if a is not b:
                difieren.append((clave, a, b))
            continue
        tol = TOLERANCIAS[_familia(clave.split("|", 1)[0])]
        if abs(a - b) > tol:
            difieren.append((clave, a, b))

    print(f"golden={len(esperado):,}  actual={len(actual):,}")
    print(f"  faltantes: {len(faltan)}  nuevos: {len(nuevos)}  divergentes: {len(difieren)}")
    for clave, a, b in difieren[:10]:
        print(f"    {clave}\n      golden={a}  actual={b}")
    return 0 if not (faltan or difieren) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verificar", action="store_true")
    args = ap.parse_args()
    con = get_conn_for(str(DEFAULT_DB_PATH))
    try:
        return verificar(con) if args.verificar else generar(con)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
