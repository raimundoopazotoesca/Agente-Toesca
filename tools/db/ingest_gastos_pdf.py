"""Ingesta robusta de GASTOS DEL FONDO desde PDFs EEFF usando pdfplumber.

Reemplaza los valores extraídos por el LLM (que sistemáticamente confunde filas
con layouts multi-columna) con extracción posicional exacta.

Uso:
  python -m tools.db.ingest_gastos_pdf --fondo TRI --all
  python -m tools.db.ingest_gastos_pdf --fondo TRI --file <pdf>
  python -m tools.db.ingest_gastos_pdf --fondo TRI --all --dry-run
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).parent.parent.parent
DB = ROOT / "memory" / "agente_toesca_v2.db"

# Mapeo nombre_fila (normalizado) -> cuenta_canonical
ROW_MAP = {
    "depreciaciones": "ER.depreciaciones",
    "remuneracion del comite de vigilancia": "ER.remun_comite",
    "comision de administracion": "ER.comision_admin",
    "honorarios por custodia y administracion": "ER.honorarios_custodia",
    "costos de transaccion": "ER.costos_transaccion",
    "otros gastos de operacion": "ER.otros_gastos",
    "total gastos de operacion": "ER.total_gastos_operacion",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    s = strip_accents(s).lower().strip()
    s = re.sub(r"\s*\(-\)\s*$", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
AMOUNT_RE = re.compile(r"^\(?([\d.]+)\)?$")


def parse_amount(txt: str) -> float | None:
    """(1.234) -> -1234000; 1.234 -> 1234000 (asume M$)."""
    if not txt or txt.strip() == "-":
        return 0.0
    m = AMOUNT_RE.match(txt.strip())
    if not m:
        return None
    num = m.group(1).replace(".", "")
    try:
        val = int(num) * 1000  # miles → pesos
    except ValueError:
        return None
    if txt.strip().startswith("(") and txt.strip().endswith(")"):
        val = -val
    return float(val)


def find_gastos_page(pdf) -> int | None:
    for i, page in enumerate(pdf.pages):
        txt = (page.extract_text() or "").lower()
        if "gastos de operaci" in strip_accents(txt) and "comision de administracion" in strip_accents(txt):
            return i
    return None


def group_rows(words: list) -> dict[int, list]:
    rows = defaultdict(list)
    for w in words:
        key = round(w["top"])
        rows[key].append(w)
    # combine near-duplicate keys (within 3px)
    keys = sorted(rows.keys())
    merged = {}
    if not keys:
        return merged
    cur = [keys[0]]
    for k in keys[1:]:
        if k - cur[-1] <= 3:
            cur.append(k)
        else:
            base = cur[0]
            merged[base] = sum([rows[c] for c in cur], [])
            cur = [k]
    merged[cur[0]] = sum([rows[c] for c in cur], [])
    return merged


def extract_gastos(pdf_path: Path) -> dict[str, dict[str, float]]:
    """Devuelve {periodo: {cuenta_canonical: monto_clp}} para todas las columnas del ER."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        idx = find_gastos_page(pdf)
        if idx is None:
            return {}
        page = pdf.pages[idx]
        words = page.extract_words()
        rows = group_rows(words)

        # Localizar los headers de fecha por columna (x_center).
        # Cada columna del ER tiene START (01/01/YYYY = YTD, o 01/04/YYYY = Q2, etc.)
        # y END (30/06/YYYY). Sólo queremos columnas YTD (start = 01/01).
        col_dates = defaultdict(dict)  # x_center -> {"starts":[dates], "ends":[dates]}
        # Recolectar todas las fechas con su x_center y su rol (start vs end) según orden
        all_dates = []
        for y in sorted(rows.keys()):
            for w in rows[y]:
                m = DATE_RE.match(w["text"])
                if m:
                    d, mo, yr = m.groups()
                    x_center = (w["x0"] + w["x1"]) / 2
                    all_dates.append({"x": x_center, "y": y, "d": d, "mo": mo, "yr": yr, "raw": w["text"]})
        if not all_dates:
            return {}
        # Agrupar por x_center (tolerancia 6 px)
        x_groups: dict[float, list] = {}
        for dt in all_dates:
            found = None
            for xk in x_groups:
                if abs(xk - dt["x"]) < 8:
                    found = xk
                    break
            if found is None:
                x_groups[dt["x"]] = [dt]
            else:
                x_groups[found].append(dt)
        # Para cada grupo x, determinar si es YTD (tiene 01/01) o Q.
        # Si NINGUNA columna tiene 01/01 (PDFs anuales de 1 sola fecha), todas se
        # consideran YTD (cierres anuales o auditados).
        any_ytd = any(
            d["d"] == "01" and d["mo"] == "01"
            for dts in x_groups.values() for d in dts
        )
        date_columns: dict[float, str] = {}
        for x, dts in x_groups.items():
            dts_sorted = sorted(dts, key=lambda d: d["y"])
            starts = [d for d in dts_sorted if d["d"] == "01" and d["mo"] == "01"]
            if len(dts_sorted) >= 2:
                end_dt = dts_sorted[1]
            else:
                end_dt = dts_sorted[0]
            is_ytd = (not any_ytd) or (len(starts) > 0)
            if is_ytd:
                periodo = f"{end_dt['yr']}-{end_dt['mo']}"
                date_columns[x] = periodo

        # Ordenar columnas por x
        cols_sorted = sorted(date_columns.items(), key=lambda x: x[0])
        if not cols_sorted:
            return {}

        # Para cada fila de gasto identificar el label y capturar los valores por columna
        result: dict[str, dict[str, float]] = {p: {} for _, p in cols_sorted}
        for y in sorted(rows.keys()):
            row_words = sorted(rows[y], key=lambda w: w["x0"])
            # label = texto concatenado hasta encontrar el primer numérico
            label_parts = []
            num_words = []
            for w in row_words:
                t = w["text"].strip()
                if AMOUNT_RE.match(t) or t == "-":
                    num_words.append(w)
                elif re.match(r"^\d+$", t) and w["x0"] > 430:
                    # nota-reference numeral (no valor de $)
                    continue
                else:
                    if not num_words:  # aún en la etiqueta
                        label_parts.append(t)
            label = norm(" ".join(label_parts))
            cuenta = None
            for k, v in ROW_MAP.items():
                if k in label:
                    cuenta = v
                    break
            if cuenta is None:
                continue
            # asignar cada num_word a la columna más cercana por x, con umbral
            # (evita capturar valores de columnas Q cuando solo tenemos YTD registrados)
            for w in num_words:
                x_center = (w["x0"] + w["x1"]) / 2
                cc = min(cols_sorted, key=lambda c: abs(c[0] - x_center))
                if abs(cc[0] - x_center) > 22:
                    continue  # valor pertenece a columna Q (no YTD) → descartar
                periodo = cc[1]
                val = parse_amount(w["text"])
                if val is None:
                    continue
                # si ya hay valor (fila con múltiples números para misma col), preferir el más cercano
                if cuenta in result[periodo]:
                    prev_dist = getattr(result[periodo], "_dist_" + cuenta, 999)
                    new_dist = abs(cc[0] - x_center)
                    if new_dist >= prev_dist:
                        continue
                result[periodo][cuenta] = val
        return result


def upsert(con: sqlite3.Connection, fondo_key: str, periodo: str, cuenta: str, monto: float, source: str, dry_run: bool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = con.cursor()
    # supersede filas existentes activas para (fondo, periodo, cuenta)
    existing = cur.execute(
        "SELECT id, monto_clp, source_file FROM raw_eeff_line WHERE fondo_key=? AND periodo=? AND cuenta_codigo_canonical=? AND superseded_at IS NULL",
        (fondo_key, periodo, cuenta),
    ).fetchall()
    same_val = any(abs((r[1] or 0) - monto) < 1 and r[2] == source for r in existing)
    if same_val and len(existing) == 1:
        return "skip"
    if not dry_run:
        if existing:
            cur.executemany(
                "UPDATE raw_eeff_line SET superseded_at=? WHERE id=?",
                [(now, r[0]) for r in existing],
            )
        cur.execute(
            """INSERT INTO raw_eeff_line
                 (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
                  source_file, source_sheet, source_row, file_hash, ingest_run_id,
                  loaded_at, cuenta_codigo_canonical)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fondo_key, periodo, None, "gastos_pdf_extractor", monto, None,
             source, "ER (pdfplumber)", None, "pdf_extract_v1", None, now, cuenta),
        )
    return "insert" if not existing else "replace"


COMPONENTES = (
    "ER.depreciaciones",
    "ER.remun_comite",
    "ER.comision_admin",
    "ER.honorarios_custodia",
    "ER.costos_transaccion",
    "ER.otros_gastos",
)


def validate_sum(cuentas: dict[str, float], tol: int = 2000) -> tuple[bool, float, float]:
    """Retorna (ok, sum_componentes, total_reportado). Tolerancia default 2K CLP."""
    total = cuentas.get("ER.total_gastos_operacion")
    if total is None:
        return (False, 0, 0)
    comp = sum((cuentas.get(k) or 0) for k in COMPONENTES)
    return (abs(comp - total) <= tol, comp, total)


def process(pdf_path: Path, fondo_key: str, con: sqlite3.Connection, dry_run: bool = False):
    print(f"[{pdf_path.name}]", flush=True)
    try:
        data = extract_gastos(pdf_path)
    except Exception as e:
        print(f"  ERROR: {e}")
        return
    if not data:
        print("  (sin gastos detectados)")
        return
    for periodo, cuentas in sorted(data.items()):
        ok, comp, total = validate_sum(cuentas)
        if not ok:
            diff = comp - total
            print(f"  {periodo}: ⚠️  SUMA NO CUADRA (sum={comp:,.0f}, total={total:,.0f}, diff={diff:,.0f}) — NO se persiste")
            continue
        actions = defaultdict(int)
        for cta, monto in cuentas.items():
            action = upsert(con, fondo_key, periodo, cta, monto, pdf_path.name, dry_run)
            actions[action] += 1
        print(f"  {periodo}: ok (total={total:,.0f})  actions={dict(actions)}")
    if not dry_run:
        con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fondo", required=True, choices=["TRI", "PT", "APO"])
    ap.add_argument("--file", help="ruta a un PDF específico")
    ap.add_argument("--all", action="store_true", help="procesa todos los PDFs de work/eeff_ingesta/<FONDO>/pdf")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.file:
        files = [Path(args.file)]
    else:
        pdf_dir = ROOT / "work" / "eeff_ingesta" / args.fondo / "pdf"
        files = sorted(pdf_dir.glob("*.pdf"))
        if not files:
            print(f"No PDFs en {pdf_dir}")
            return

    con = sqlite3.connect(str(DB))
    try:
        for f in files:
            process(f, args.fondo, con, dry_run=args.dry_run)
    finally:
        con.close()


if __name__ == "__main__":
    main()
