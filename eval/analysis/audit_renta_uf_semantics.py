"""Fase 0 — Demuestra qué representa cada campo de renta en raw_rent_roll_line.

Contexto: el plan JLL v2 fija `renta_uf` = total UF y `renta_uf_m2` = tasa UF/m².
Antes de cambiar la semántica del histórico hay que demostrar qué es hoy cada
campo. Este script no escribe nada: sólo lee y reporta.

Uso:
    python eval/analysis/audit_renta_uf_semantics.py [--db RUTA]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict

TOL = 0.01  # 1% de tolerancia relativa


def _rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT activo_key, periodo, unidad, arrendatario, m2, renta_uf, extra_json
          FROM raw_rent_roll_line
         WHERE superseded_at IS NULL
           AND extra_json IS NOT NULL
        """
    ).fetchall()


def _close(a: float | None, b: float | None, tol: float = TOL) -> bool:
    if a is None or b is None:
        return False
    if abs(b) < 1e-9:
        return abs(a) < 1e-9
    return abs(a - b) / abs(b) <= tol


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="memory/agente_toesca_v2.db")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Hipótesis evaluadas sobre CADA fila (no mezclando filas distintas, que fue
    # el error que motivó esta auditoría).
    hyps = {
        "renta_uf == renta_real / m2": lambda r: _close(r["renta_uf"], r["renta_real"] / r["m2"]),
        "renta_uf == renta_esp_total / m2": lambda r: _close(r["renta_uf"], r["renta_esp_total"] / r["m2"]),
        "renta_uf == renta_esp_pond / m2": lambda r: _close(r["renta_uf"], r["renta_esp_pond"] / r["m2"]),
        "renta_uf * m2 == renta_real": lambda r: _close(r["renta_uf"] * r["m2"], r["renta_real"]),
        "renta_uf * m2 == renta_esp_total": lambda r: _close(r["renta_uf"] * r["m2"], r["renta_esp_total"]),
        "renta_uf == renta_real (total)": lambda r: _close(r["renta_uf"], r["renta_real"]),
    }

    stats: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )  # activo -> hip -> [ok, evaluables]
    n_total = n_util = 0
    ejemplos: dict[str, dict] = {}

    for row in _rows(conn):
        n_total += 1
        try:
            ex = json.loads(row["extra_json"])
        except (TypeError, ValueError):
            continue
        m2 = row["m2"]
        if not m2 or m2 <= 0 or row["renta_uf"] in (None, 0):
            continue
        rec = {
            "renta_uf": row["renta_uf"],
            "m2": m2,
            "renta_real": ex.get("renta_real"),
            "renta_esp_total": ex.get("renta_esperada_total"),
            "renta_esp_pond": ex.get("renta_esperada_ponderada"),
        }
        if rec["renta_real"] is None and rec["renta_esp_total"] is None:
            continue
        n_util += 1
        act = row["activo_key"]
        for nombre, fn in hyps.items():
            try:
                ok = bool(fn(rec))
            except (TypeError, ZeroDivisionError):
                continue
            stats[act][nombre][1] += 1
            stats[act][nombre][0] += int(ok)
        ejemplos.setdefault(act, {**rec, "unidad": row["unidad"], "periodo": row["periodo"]})

    print(f"DB: {args.db}")
    print(f"filas vivas con extra_json: {n_total} | evaluables: {n_util}\n")

    print("Hipótesis por activo (aciertos / evaluables):")
    nombres = list(hyps)
    ancho = max(len(n) for n in nombres)
    for act in sorted(stats):
        print(f"\n  {act}")
        for nombre in nombres:
            ok, tot = stats[act][nombre]
            if not tot:
                continue
            pct = 100 * ok / tot
            marca = "  <== CIERRA" if pct >= 99 else ""
            print(f"    {nombre:{ancho}s}  {ok:5d}/{tot:5d}  {pct:5.1f}%{marca}")

    print("\nEjemplo por activo (misma fila, para inspección manual):")
    for act, e in sorted(ejemplos.items()):
        print(
            f"  {act:12s} {e['periodo']} u={str(e['unidad'])[:10]:10s} "
            f"m2={e['m2']:8.1f} renta_uf={e['renta_uf']:8.3f} "
            f"real={e['renta_real']} esp_total={e['renta_esp_total']} "
            f"esp_pond={e['renta_esp_pond']}"
        )

    conn.close()


if __name__ == "__main__":
    main()
