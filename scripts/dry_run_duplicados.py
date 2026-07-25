"""Dry run del saneamiento de duplicados de raw_eeff_line. NO escribe nada.

Aplica la política de tres casos definida por el usuario (2026-07-24):

  Caso 1 — duplicado exacto: mismo file_hash, misma source_row y mismos valores.
           Sobrevive la primera ingesta válida y trazable; el resto se marca
           superseded. No se borra físicamente.

  Caso 2 — misma clave de negocio y mismos valores, distinto archivo.
           Sobrevive la versión del flujo validado y confirmado; si ambas tienen
           la misma calidad, la primera ingesta válida. El resto, redundante.

  Caso 3 — misma clave de negocio, valores diferentes.
           NO es automáticamente un duplicado: puede ser una corrección. Solo
           reemplaza si hay evidencia de corrección deliberada; si no se puede
           determinar, el grupo se detiene para revisión humana.

Prioridad para elegir sobreviviente:
  1. ingesta validada y confirmada   2. ingest_run_id válido
  3. fuente y hash identificables    4. registro vigente
  5. reingesta explícita             6. revisión humana si divergen sin
                                        precedencia demostrable

Uso:
    python scripts/dry_run_duplicados.py            # resumen
    python scripts/dry_run_duplicados.py --detalle  # + ejemplos por caso
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db.connection import DEFAULT_DB_PATH, get_conn_for  # noqa: E402

# Un source_file de la ruta validada (web + confirmación humana) tiene prioridad
# sobre las cargas por CLI/batch.
PREFIJOS_VALIDADOS = ("chatgpt_manual",)

TOLERANCIA = 0.01  # CLP: diferencias por redondeo no cuentan como divergencia


def _es_validado(source_file: str | None) -> bool:
    return bool(source_file) and source_file.startswith(PREFIJOS_VALIDADOS)


def _prioridad(fila: dict) -> tuple:
    """Menor es mejor. Refleja el orden de prioridad acordado."""
    return (
        0 if _es_validado(fila["source_file"]) else 1,   # 1. flujo validado
        0 if fila["run_valido"] else 1,                  # 2. ingest_run_id válido
        0 if fila["file_hash"] else 1,                   # 3. hash identificable
        fila["id"],                                      # 4/5. primera ingesta válida
    )


def analizar(con) -> dict:
    filas = con.execute(
        """
        SELECT r.id, r.fondo_key, r.periodo,
               COALESCE(r.cuenta_codigo_canonical, r.cuenta_codigo, r.cuenta_nombre) AS clave,
               r.monto_clp, r.source_file, r.source_row, r.file_hash, r.loaded_at,
               (r.ingest_run_id IS NOT NULL
                AND EXISTS (SELECT 1 FROM ingest_run i WHERE i.id = r.ingest_run_id)) AS run_valido
          FROM raw_eeff_line r
         WHERE r.superseded_at IS NULL
        """
    ).fetchall()

    grupos: dict[tuple, list[dict]] = defaultdict(list)
    for f in filas:
        d = dict(f)
        grupos[(d["fondo_key"], d["periodo"], d["clave"])].append(d)

    res = {
        "filas_vivas": len(filas),
        "grupos_totales": len(grupos),
        "casos": Counter(),
        "filas_por_caso": Counter(),
        "vigentes": 0,
        "superseded": 0,
        "ambiguos": [],
        "ejemplos": defaultdict(list),
        "impacto_por_fondo": defaultdict(lambda: {"grupos": 0, "superseded": 0}),
        "periodos_afectados": set(),
    }

    for clave, filas_g in grupos.items():
        if len(filas_g) == 1:
            res["vigentes"] += 1
            continue

        montos = {round(f["monto_clp"], 2) if f["monto_clp"] is not None else None for f in filas_g}
        valores_iguales = len(montos) == 1 or (
            len(montos) > 1
            and None not in montos
            and (max(montos) - min(montos)) <= TOLERANCIA
        )
        hashes = {f["file_hash"] for f in filas_g}
        rows = {f["source_row"] for f in filas_g}

        if valores_iguales and len(hashes) == 1 and len(rows) == 1:
            caso = "1_exacto"
        elif valores_iguales:
            caso = "2_redundante"
        else:
            caso = "3_valores_distintos"

        ordenadas = sorted(filas_g, key=_prioridad)
        sobreviviente, resto = ordenadas[0], ordenadas[1:]

        if caso == "3_valores_distintos":
            # ¿Hay precedencia demostrable? Solo si el mejor candidato viene del
            # flujo validado y los demás no, o si tiene run válido y los otros no.
            mejor, siguiente = _prioridad(ordenadas[0]), _prioridad(ordenadas[1])
            demostrable = mejor[:3] < siguiente[:3]
            if not demostrable:
                res["ambiguos"].append({
                    "clave": clave,
                    "filas": [
                        {k: f[k] for k in ("id", "monto_clp", "source_file", "loaded_at")}
                        for f in ordenadas
                    ],
                })
                res["casos"]["3_AMBIGUO_revision_humana"] += 1
                res["filas_por_caso"]["3_AMBIGUO_revision_humana"] += len(filas_g)
                continue

        res["casos"][caso] += 1
        res["filas_por_caso"][caso] += len(filas_g)
        res["vigentes"] += 1
        res["superseded"] += len(resto)
        res["periodos_afectados"].add(clave[1])
        imp = res["impacto_por_fondo"][clave[0]]
        imp["grupos"] += 1
        imp["superseded"] += len(resto)
        if len(res["ejemplos"][caso]) < 3:
            res["ejemplos"][caso].append((clave, sobreviviente, resto))

    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalle", action="store_true")
    args = ap.parse_args()

    con = get_conn_for(str(DEFAULT_DB_PATH))
    try:
        r = analizar(con)
        suma_antes = con.execute(
            "SELECT ROUND(SUM(monto_clp), 2) FROM raw_eeff_line WHERE superseded_at IS NULL"
        ).fetchone()[0]
    finally:
        con.close()

    print("═" * 74)
    print("DRY RUN — saneamiento de duplicados en raw_eeff_line (no escribe nada)")
    print("═" * 74)
    print(f"\nFilas vivas analizadas : {r['filas_vivas']:,}")
    print(f"Grupos de clave de negocio (fondo, periodo, cuenta): {r['grupos_totales']:,}")

    print("\n── Grupos duplicados por caso ──────────────────────────────────────")
    print(f"{'caso':34} {'grupos':>8} {'filas':>8}")
    for caso in sorted(r["casos"]):
        print(f"{caso:34} {r['casos'][caso]:>8,} {r['filas_por_caso'][caso]:>8,}")

    print("\n── Resultado del saneamiento ───────────────────────────────────────")
    print(f"  Filas que quedarían vigentes  : {r['filas_vivas'] - r['superseded']:,}")
    print(f"  Filas que quedarían superseded: {r['superseded']:,}")
    print(f"  Grupos detenidos para revisión: {r['casos'].get('3_AMBIGUO_revision_humana', 0):,}")
    print(f"  Períodos afectados            : {len(r['periodos_afectados'])}")

    print("\n── Impacto por fondo ───────────────────────────────────────────────")
    print(f"{'fondo':8} {'grupos':>8} {'filas superseded':>18}")
    for fondo, imp in sorted(r["impacto_por_fondo"].items()):
        print(f"{fondo:8} {imp['grupos']:>8,} {imp['superseded']:>18,}")

    print("\n── Impacto en cifras ───────────────────────────────────────────────")
    print(f"  Suma de monto_clp de filas vivas ANTES : {suma_antes:,.0f}")
    print("  Nota: el saneamiento NO cambia el valor de ninguna fila; solo marca")
    print("  superseded las redundantes. Toda consulta que hoy sume sin agrupar")
    print("  está contando de más — ahí está el impacto real.")

    if args.detalle:
        print("\n── Ejemplos por caso ───────────────────────────────────────────────")
        for caso, ejemplos in sorted(r["ejemplos"].items()):
            print(f"\n  [{caso}]")
            for clave, sobrevive, resto in ejemplos:
                print(f"    {clave}")
                print(f"      vigente : id={sobrevive['id']} monto={sobrevive['monto_clp']} "
                      f"src={sobrevive['source_file']}")
                for x in resto[:2]:
                    print(f"      superseded: id={x['id']} monto={x['monto_clp']} src={x['source_file']}")

        if r["ambiguos"]:
            print(f"\n── Casos ambiguos (detenidos): {len(r['ambiguos'])} ──────────────────")
            for a in r["ambiguos"][:10]:
                print(f"    {a['clave']}")
                for f in a["filas"][:3]:
                    print(f"      id={f['id']} monto={f['monto_clp']} src={f['source_file']} "
                          f"cargado={f['loaded_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
