"""Deduplica raw_eeff_line marcando filas superseded.

Bugs históricos que resuelve:
1. Intra-file: el LLM ingesta 2 columnas (trimestre y YTD) con el mismo `periodo`, causando
   2 filas por (fondo, periodo, cuenta, source_file). Solución: keep row with MAX(abs(monto))
   — YTD siempre >= trimestre solo.
2. Inter-file: PDFs trimestrales incluyen columnas comparativas del año anterior. Esas filas
   se ingestan con su periodo real, causando duplicados desde múltiples source_file para el
   mismo (fondo, periodo, cuenta). Solución: preferir el PDF cuyo periodo de reporte
   coincide con el periodo de la fila (source primario).

Uso:
  python -m tools.db.dedup_raw_eeff --dry-run   # simula
  python -m tools.db.dedup_raw_eeff              # aplica
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent.parent.parent / "memory" / "agente_toesca_v2.db"


def report_date_from_filename(name: str) -> str | None:
    """Extrae YYYY-MM del filename del PDF (fecha del reporte).
    Retorna None si no matchea patrones conocidos.
    """
    # 2509 EEFF... / 2506 EEFF... (YYMM al inicio)
    m = re.match(r"^(\d{2})(\d{2})\s*(?:EEFF|EF|Fondo|Toesca)", name, re.IGNORECASE)
    if m:
        yy, mm = m.groups()
        if 1 <= int(mm) <= 12:
            return f"20{yy}-{mm}"
    # 0325 Fondo... / 0225 ... (MMYY al inicio)
    m = re.match(r"^(\d{2})(\d{2})\s+", name)
    if m:
        a, b = m.groups()
        # Si el primero es válido como mes y el segundo como año YY
        if 1 <= int(a) <= 12 and int(b) >= 17:
            return f"20{b}-{a}"
        if 1 <= int(b) <= 12 and int(a) >= 17:
            return f"20{a}-{b}"
    # 12.20 / 06.22 / 12.21
    m = re.search(r"(\d{2})\.(\d{2})\s", name)
    if m:
        mm, yy = m.groups()
        if 1 <= int(mm) <= 12:
            return f"20{yy}-{mm}"
    # 220331, 220930, 231231, 240331, 240630, 240930, 241231, 250331
    m = re.match(r"^(\d{2})(\d{2})(\d{2})\s+EEFF", name)
    if m:
        yy, mm, _ = m.groups()
        if 1 <= int(mm) <= 12:
            return f"20{yy}-{mm}"
    # 31122018, 31032019
    m = re.match(r"^(\d{2})(\d{2})(\d{4})\s+EEFF", name)
    if m:
        _, mm, yyyy = m.groups()
        if 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"
    # EEFF Toesca ... 032018 / 062018 / 092018 / 122018
    m = re.search(r"\s(\d{2})(20\d{2})\.\w+$", name)
    if m:
        mm, yyyy = m.groups()
        if 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"
    # 2018.6 rev / 2018 09 rev
    m = re.search(r"(20\d{2})\s?(\d{2})", name)
    if m:
        yyyy, mm = m.groups()
        if 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"
    # 20{YY}{MM} sin espacio (ej: 201906, 202009 en nombre de docx)
    m = re.search(r"(20\d{2})(\d{2})", name)
    if m:
        yyyy, mm = m.groups()
        if 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"
    # "2025 EEFF ..." (año solo → asumir cierre de año, dic)
    m = re.match(r"^(20\d{2})\s+EEFF", name)
    if m:
        return f"{m.group(1)}-12"
    return None


def dedup(con: sqlite3.Connection, dry_run: bool = False):
    cur = con.cursor()

    # ==== PASO 1: intra-file dedup ====
    # Para cada (fondo, periodo, cuenta_canonical, source_file), keep MAX(abs(monto))
    rows = cur.execute(
        """SELECT id, fondo_key, periodo, cuenta_codigo_canonical, source_file, monto_clp
           FROM raw_eeff_line
           WHERE cuenta_codigo_canonical IS NOT NULL
             AND superseded_at IS NULL"""
    ).fetchall()

    grupos_intra = defaultdict(list)  # (fondo, periodo, cuenta, source) -> [(id, monto), ...]
    for rid, fondo, periodo, cuenta, source, monto in rows:
        grupos_intra[(fondo, periodo, cuenta, source)].append((rid, monto))

    to_supersede_intra = []
    for key, lst in grupos_intra.items():
        if len(lst) <= 1:
            continue
        # keep max abs, supersede resto
        lst_sorted = sorted(lst, key=lambda x: abs(x[1] or 0), reverse=True)
        keeper = lst_sorted[0][0]
        for rid, _ in lst_sorted[1:]:
            to_supersede_intra.append(rid)

    print(f"Intra-file: {len(grupos_intra)} grupos, marcando {len(to_supersede_intra)} filas duplicadas")

    if not dry_run and to_supersede_intra:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.executemany(
            "UPDATE raw_eeff_line SET superseded_at=? WHERE id=?",
            [(now, rid) for rid in to_supersede_intra],
        )
        con.commit()

    # ==== PASO 2: inter-file dedup ====
    # Recargar filas activas
    rows2 = cur.execute(
        """SELECT id, fondo_key, periodo, cuenta_codigo_canonical, source_file, monto_clp
           FROM raw_eeff_line
           WHERE cuenta_codigo_canonical IS NOT NULL
             AND superseded_at IS NULL"""
    ).fetchall()

    grupos_inter = defaultdict(list)  # (fondo, periodo, cuenta) -> [(id, source_file, monto), ...]
    for rid, fondo, periodo, cuenta, source, monto in rows2:
        grupos_inter[(fondo, periodo, cuenta)].append((rid, source, monto))

    to_supersede_inter = []
    sin_primario = 0
    for (fondo, periodo, cuenta), lst in grupos_inter.items():
        if len(lst) <= 1:
            continue
        # score cada fuente: 100 si su fecha de reporte == periodo, si no, distancia
        def score(source):
            rd = report_date_from_filename(source)
            if rd is None:
                return -1
            if rd == periodo:
                return 100
            # distancia en meses; preferir reportes CERCANOS al periodo, pero no anteriores
            try:
                y1, m1 = int(rd[:4]), int(rd[5:7])
                y2, m2 = int(periodo[:4]), int(periodo[5:7])
                diff = (y1 - y2) * 12 + (m1 - m2)
                if diff < 0:
                    return -2  # reportado antes del periodo → no puede tenerlo
                return 50 - diff  # más cercano = mejor
            except Exception:
                return -3

        scored = sorted(lst, key=lambda x: score(x[1]), reverse=True)
        # keep el de mayor score
        keeper = scored[0]
        if score(keeper[1]) < 0:
            sin_primario += 1
            # fallback: keep el de mayor abs(monto) para no borrar todo
            fb = sorted(lst, key=lambda x: abs(x[2] or 0), reverse=True)[0]
            keeper = fb
        for rid, src, _ in lst:
            if rid != keeper[0]:
                to_supersede_inter.append(rid)

    print(f"Inter-file: {len(grupos_inter)} grupos, marcando {len(to_supersede_inter)} filas; sin primario detectado: {sin_primario}")

    if not dry_run and to_supersede_inter:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.executemany(
            "UPDATE raw_eeff_line SET superseded_at=? WHERE id=?",
            [(now, rid) for rid in to_supersede_inter],
        )
        con.commit()

    print(f"\nTOTAL filas marcadas superseded: {len(to_supersede_intra) + len(to_supersede_inter)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB))
    try:
        dedup(con, dry_run=args.dry_run)
    finally:
        con.close()


if __name__ == "__main__":
    main()
