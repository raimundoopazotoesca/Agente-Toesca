"""Reporte de cobertura del mapeo canónico de cuentas. Solo lectura.

Mide dos cosas distintas, a propósito:

  COBERTURA POR FILAS       cuántas filas tienen `cuenta_codigo_canonical`.
                            Útil para dimensionar el trabajo pendiente.
  COBERTURA FUNCIONAL       si las cuentas que realmente alimentan el factsheet,
                            los KPIs y el Asistente están completas por fondo y
                            período. Es la que importa.

Subir el porcentaje de filas no sirve si se logra mapeando filas frecuentes pero
inútiles: por eso la cobertura funcional se reporta aparte y es la que define si
la Etapa 1 del plan de mapeo está cumplida.

Uso:
    python scripts/reporte_cobertura_mapeo.py                # resumen
    python scripts/reporte_cobertura_mapeo.py --criticas     # detalle funcional
    python scripts/reporte_cobertura_mapeo.py --pendientes N # top N por mapear
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db.connection import DEFAULT_DB_PATH, get_conn_for  # noqa: E402

# Cuentas que alimentan outputs vigentes, CADA UNA CONTRA SU TABLA REAL.
#
# Importa distinguirlas: el balance del factsheet NO sale de `raw_eeff_line` sino
# de `raw_balance_consolidado_line`, que tiene su propia ingesta (tab "Balance
# Consolidado"). Medir las cuentas ESF contra raw_eeff_line producía 515 huecos
# falsos — un ejemplo de por qué la cobertura tiene que medirse por relevancia
# funcional y no por volumen de filas.
#
# Fuente: scripts/build_factsheet.py — `gasto_cuentas` (línea ~645) y la query de
# balance (línea ~591). Si el factsheet empieza a usar otra cuenta, agregarla aquí:
# este set es el contrato de la Etapa 1 del plan de mapeo.

# Gastos del fondo: SÍ salen de raw_eeff_line vía cuenta_codigo_canonical.
CUENTAS_ER_EEFF = (
    "ER.comision_admin",
    "ER.honorarios_custodia",
    "ER.otros_gastos",
    "ER.remun_comite",
    "ER.costos_transaccion",
    "ER.total_gastos_operacion",
)

# Balance: sale de raw_balance_consolidado_line (ingesta propia, trimestral).
CUENTAS_ESF_BALANCE = (
    "ESF.efectivo",
    "ESF.propiedades_inversion",
    "ESF.otros_activos_corrientes",
    "ESF.otros_activos_no_corrientes",
    "ESF.total_activo",
    "ESF.prestamos",
    "ESF.pasivos_impuestos_diferidos",
    "ESF.otros_pasivos",
    "ESF.patrimonio_neto",
    "ESF.total_pasivo_patrimonio",
)

# Derivadas en el propio output: no se mapean ni se miden.
#   ER.recurrentes = ER.honorarios_custodia + ER.remun_comite  (calculada en el JS)
CUENTAS_DERIVADAS = ("ER.recurrentes",)

CUENTAS_CRITICAS = CUENTAS_ER_EEFF  # las que dependen del mapeo canónico

# Ausencias verificadas una por una contra la fuente: la cuenta NO figura en el
# documento de ese período, así que no es un hueco de mapeo. Sin esta lista la
# métrica confunde "falta mapear" con "no existe", que son problemas distintos.
# Ver migración 069 para el detalle del veredicto de cada caso.
AUSENCIAS_LEGITIMAS = {
    # Apo: "Costos de transacción" no figura en el EEFF de esos cierres.
    ("Apo", "2019-03", "ER.costos_transaccion"),
    ("Apo", "2019-06", "ER.costos_transaccion"),
    ("Apo", "2019-09", "ER.costos_transaccion"),
    ("Apo", "2019-12", "ER.costos_transaccion"),
    ("Apo", "2020-03", "ER.costos_transaccion"),
    ("Apo", "2025-09", "ER.costos_transaccion"),
    ("Apo", "2025-12", "ER.costos_transaccion"),
    # Apo: lo único parecido es "Otros gastos de operación pagados", que es EFE.
    ("Apo", "2025-09", "ER.otros_gastos"),
    ("Apo", "2025-12", "ER.otros_gastos"),
    # PT inició operaciones el 16-nov-2017: a junio no tenía gastos desglosados.
    ("PT", "2017-06", "ER.comision_admin"),
    ("PT", "2017-06", "ER.honorarios_custodia"),
    ("PT", "2017-06", "ER.remun_comite"),
    ("PT", "2017-06", "ER.costos_transaccion"),
    ("PT", "2017-06", "ER.total_gastos_operacion"),
}


# Períodos en los que se espera ver estas cuentas: cierres trimestrales.
def _es_cierre(periodo: str) -> bool:
    return periodo[5:7] in ("03", "06", "09", "12")


def cobertura_por_filas(con) -> None:
    print("── Cobertura por filas (raw_eeff_line vivas) ───────────────────────")
    tot, map_ = con.execute(
        "SELECT COUNT(*), SUM(cuenta_codigo_canonical IS NOT NULL) "
        "FROM raw_eeff_line WHERE superseded_at IS NULL"
    ).fetchone()
    print(f"  global: {map_:,} / {tot:,} = {100*map_/tot:.1f}%\n")

    print(f"  {'fondo':6} {'mapeadas':>10} {'total':>10} {'%':>7}")
    for r in con.execute(
        "SELECT fondo_key, COUNT(*) n, SUM(cuenta_codigo_canonical IS NOT NULL) m "
        "FROM raw_eeff_line WHERE superseded_at IS NULL GROUP BY 1 ORDER BY n DESC"
    ):
        print(f"  {r[0]:6} {r[2]:>10,} {r[1]:>10,} {100*r[2]/r[1]:>6.1f}%")

    print(f"\n  {'sección':16} {'filas':>10}")
    for r in con.execute(
        "SELECT COALESCE(seccion,'(sin sección)') s, COUNT(*) n "
        "FROM raw_eeff_line WHERE superseded_at IS NULL GROUP BY 1 ORDER BY n DESC"
    ):
        print(f"  {r[0]:16} {r[1]:>10,}")

    print(f"\n  {'año':6} {'filas':>10} {'%mapeado':>10}")
    for r in con.execute(
        "SELECT substr(periodo,1,4) a, COUNT(*) n, "
        "       ROUND(100.0*SUM(cuenta_codigo_canonical IS NOT NULL)/COUNT(*),1) p "
        "FROM raw_eeff_line WHERE superseded_at IS NULL GROUP BY 1 ORDER BY 1"
    ):
        print(f"  {r[0]:6} {r[1]:>10,} {r[2]:>9}%")

    print(f"\n  {'tipo de ingesta':34} {'filas':>10} {'%mapeado':>10}")
    for r in con.execute(
        """SELECT CASE
                    WHEN lineage_status IS NOT NULL THEN lineage_status
                    WHEN source_file LIKE 'chatgpt_manual%' THEN 'web validada (chatgpt)'
                    WHEN source_file LIKE '%.json' THEN 'CLI json'
                    WHEN source_file LIKE '%.pdf'  THEN 'CLI pdf'
                    ELSE 'otro' END tipo,
                  COUNT(*) n,
                  ROUND(100.0*SUM(cuenta_codigo_canonical IS NOT NULL)/COUNT(*),1) p
             FROM raw_eeff_line WHERE superseded_at IS NULL GROUP BY 1 ORDER BY n DESC"""
    ):
        print(f"  {r[0]:34} {r[1]:>10,} {r[2]:>9}%")


def cobertura_funcional(con, detalle: bool = False) -> int:
    print("\n── Cobertura funcional (cuentas que alimentan outputs) ─────────────")
    print("  Etapa 1 del plan de mapeo: las cuentas de gasto del factsheet deben")
    print("  estar completas por fondo y cierre. Es el criterio real, no el % de")
    print("  filas: mapear nombres frecuentes pero inútiles no mueve esta cifra.\n")

    fondos = [r[0] for r in con.execute("SELECT fondo_key FROM dim_fondo ORDER BY fondo_key")]
    faltantes_totales = 0

    print(f"  Gastos del fondo (raw_eeff_line → depende del mapeo canónico)")
    print(f"  {'fondo':6} {'cierres':>9} {'cuentas ok':>12} {'esperadas':>11} {'%':>7}")
    detalle_filas = []
    ausentes = 0
    for fondo in fondos:
        cierres = [
            p for (p,) in con.execute(
                "SELECT DISTINCT periodo FROM raw_eeff_line "
                "WHERE fondo_key=? AND superseded_at IS NULL ORDER BY periodo", (fondo,)
            ) if _es_cierre(p)
        ]
        if not cierres:
            continue
        presentes = 0
        for periodo in cierres:
            hay = {
                r[0] for r in con.execute(
                    "SELECT DISTINCT cuenta_codigo_canonical FROM raw_eeff_line "
                    "WHERE fondo_key=? AND periodo=? AND superseded_at IS NULL "
                    "  AND cuenta_codigo_canonical IS NOT NULL",
                    (fondo, periodo),
                )
            }
            faltan = [
                c for c in CUENTAS_CRITICAS
                if c not in hay and (fondo, periodo, c) not in AUSENCIAS_LEGITIMAS
            ]
            ausentes += sum(
                1 for c in CUENTAS_CRITICAS
                if c not in hay and (fondo, periodo, c) in AUSENCIAS_LEGITIMAS
            )
            presentes += len(CUENTAS_CRITICAS) - len(faltan)
            if faltan:
                detalle_filas.append((fondo, periodo, faltan))
        esperadas = len(cierres) * len(CUENTAS_CRITICAS)
        faltantes_totales += esperadas - presentes
        print(f"  {fondo:6} {len(cierres):>9} {presentes:>12,} {esperadas:>11,} "
              f"{100*presentes/esperadas:>6.1f}%")

    if detalle and detalle_filas:
        print(f"\n  Cierres con cuentas de gasto faltantes: {len(detalle_filas)}")
        print("  (los 12 más recientes)")
        for fondo, periodo, faltan in sorted(detalle_filas, key=lambda x: x[1], reverse=True)[:12]:
            print(f"    {fondo:5} {periodo}  faltan {len(faltan)}: {', '.join(faltan)}")

    # ── Balance: otra tabla, otra ingesta. No depende del mapeo canónico. ──
    print(f"\n  Balance del factsheet (raw_balance_consolidado_line → ingesta propia)")
    print(f"  {'fondo':6} {'periodos':>9} {'cuentas ok':>12} {'esperadas':>11} {'%':>7}")
    for fondo in fondos:
        periodos = [p for (p,) in con.execute(
            "SELECT DISTINCT periodo FROM raw_balance_consolidado_line "
            "WHERE fondo_key=? AND superseded_at IS NULL ORDER BY periodo", (fondo,)
        )]
        if not periodos:
            print(f"  {fondo:6} {0:>9} {'—':>12} {'—':>11} {'sin datos':>7}")
            continue
        presentes = 0
        for periodo in periodos:
            hay = {r[0] for r in con.execute(
                "SELECT DISTINCT cuenta_codigo FROM raw_balance_consolidado_line "
                "WHERE fondo_key=? AND periodo=? AND superseded_at IS NULL", (fondo, periodo))}
            presentes += sum(1 for c in CUENTAS_ESF_BALANCE if c in hay)
        esperadas = len(periodos) * len(CUENTAS_ESF_BALANCE)
        print(f"  {fondo:6} {len(periodos):>9} {presentes:>12,} {esperadas:>11,} "
              f"{100*presentes/esperadas:>6.1f}%")

    print(f"\n  Derivadas en el output, no se mapean: {', '.join(CUENTAS_DERIVADAS)}")
    print(f"  Ausencias verificadas contra la fuente (no son huecos): {ausentes}")
    return faltantes_totales


def pendientes(con, n: int) -> None:
    print(f"\n── Top {n} nombres por mapear (excluye métricas de serie) ───────────")
    print("  Nota: NO son N asignaciones automáticas. Cada una exige fondo,")
    print("  documento, sección, signo y ubicación. Los genéricos ('Total',")
    print("  'Otros') no se mapean sin sección que los desambigüe.\n")
    total = con.execute(
        "SELECT COUNT(*) FROM raw_eeff_line WHERE superseded_at IS NULL "
        "  AND cuenta_codigo_canonical IS NULL AND COALESCE(seccion,'') <> 'METRICA_SERIE'"
    ).fetchone()[0]
    filas = con.execute(
        """SELECT cuenta_nombre, COUNT(*) n, COUNT(DISTINCT fondo_key) fondos,
                  COUNT(DISTINCT source_file) archivos
             FROM raw_eeff_line
            WHERE superseded_at IS NULL AND cuenta_codigo_canonical IS NULL
              AND COALESCE(seccion,'') <> 'METRICA_SERIE'
            GROUP BY 1 ORDER BY n DESC LIMIT ?""", (n,)
    ).fetchall()
    generico = {"total", "otros", "otro", "totales"}
    acum = 0
    print(f"  {'nombre':52} {'filas':>6} {'fondos':>7} {'acum%':>7}  nota")
    for r in filas:
        acum += r[1]
        nota = "GENÉRICO: requiere sección" if r[0].strip().lower() in generico else ""
        print(f"  {r[0][:50]:52} {r[1]:>6} {r[2]:>7} {100*acum/total:>6.1f}%  {nota}")
    print(f"\n  Estos {len(filas)} nombres cubren {100*acum/total:.1f}% de las "
          f"{total:,} filas contables sin mapear.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--criticas", action="store_true", help="detalle de cuentas críticas faltantes")
    ap.add_argument("--pendientes", type=int, metavar="N", help="top N nombres por mapear")
    args = ap.parse_args()

    con = get_conn_for(str(DEFAULT_DB_PATH))
    try:
        print("═" * 70)
        print("COBERTURA DEL MAPEO CANÓNICO DE CUENTAS")
        print("═" * 70 + "\n")
        cobertura_por_filas(con)
        faltantes = cobertura_funcional(con, detalle=args.criticas)
        if args.pendientes:
            pendientes(con, args.pendientes)
        print(f"\n  Huecos de cuentas críticas: {faltantes:,}")
        print("  Etapa 1 se considera cumplida cuando este número sea 0.")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
