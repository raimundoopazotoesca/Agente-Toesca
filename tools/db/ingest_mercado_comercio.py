"""Ingesta de datos de mercado de comercio minorista RM (CNC, mensual)
desde texto copy-paste de la fila "Ventas del Comercio Acumuladas" del
PDF mensual de CNC.

Formato de entrada esperado: una línea con 7 valores en el orden fijo de
CATEGORIAS_ORDEN, separados por espacio/tab, "%" opcional, "-" como null:

    -0,9% 6,2% -3,0% -9,1% 0,2% -0,6% -1,2%

Se ignoran líneas de encabezado (cualquier línea que no tenga exactamente
7 tokens numéricos/"-").

No expone CLI; lo consume scripts/ingesta_server.py (Flask).
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

sys.path.insert(0, str(ROOT))
from tools.db.connection import get_conn_for  # noqa: E402

# Orden fijo — idéntico a S.page3.centros_comerciales.categorias en
# build_factsheet.py. La fuente (Excel/PDF CNC) llama a la última columna
# "Supermercado Tradicional"; el fact sheet la muestra como "Supermercados".
CATEGORIAS_ORDEN = (
    "Total Comercio", "Vestuario", "Calzado", "Artefactos Eléctricos",
    "Línea Hogar", "Muebles", "Supermercados",
)


def _parse_num_cl(raw: str) -> float | None:
    """Convierte formato numérico chileno (con % opcional) a fracción, o
    None si es '-'.

    '0,7%'  -> 0.007   (coma = decimal, se descarta el %, se divide /100)
    '-0,9%' -> -0.009
    '-'     -> None
    """
    s = raw.strip().rstrip("%").strip()
    if s == "-":
        return None
    s = s.replace(".", "").replace(",", ".")
    return float(s) / 100.0


def _looks_like_valor(tok: str) -> bool:
    if tok == "-":
        return True
    s = tok.rstrip("%").replace(".", "").replace(",", ".")
    try:
        float(s)
        return True
    except ValueError:
        return False


def parse_fila_comercio(texto: str) -> dict[str, float | None] | None:
    """Busca, entre las líneas del texto pegado, la primera con exactamente
    7 tokens numéricos/"-" y la mapea a CATEGORIAS_ORDEN.

    Retorna None si ninguna línea calza.
    """
    for line in texto.strip().splitlines():
        tokens = line.split()
        if len(tokens) != len(CATEGORIAS_ORDEN):
            continue
        if not all(_looks_like_valor(t) for t in tokens):
            continue
        valores = [_parse_num_cl(t) for t in tokens]
        return dict(zip(CATEGORIAS_ORDEN, valores))
    return None


class ValidationResult:
    """Resultado de validación con errores, warnings y datos parseados."""
    def __init__(self):
        self.ok = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.data: dict = {}

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.ok = False

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, **self.data}


def validate(texto: str, periodo: str) -> ValidationResult:
    """Valida que el texto contenga una fila con las 7 categorías.

    Retorna ValidationResult con ok=True/False, errores, warnings, y datos parseados.
    """
    result = ValidationResult()

    if not periodo:
        result.add_error("Falta declarar el período (YYYY-MM) del informe.")
        return result
    if not texto.strip():
        result.add_error("Pega la fila de valores antes de validar.")
        return result

    fila = parse_fila_comercio(texto)
    if fila is None:
        result.add_error(
            "No se detectó una fila válida — revisa que el texto pegado tenga "
            "exactamente 7 valores numéricos o '-' (Total Comercio, Vestuario, "
            "Calzado, Artefactos Eléctricos, Línea Hogar, Muebles, Supermercados)."
        )
        return result

    for categoria, valor in fila.items():
        if valor is not None and abs(valor) > 1:
            result.add_error(f"{categoria}: valor fuera de rango razonable ({valor * 100:.1f}%)")

    if not result.ok:
        return result

    fhash = hashlib.sha256(f"{periodo}|{texto.strip()}".encode("utf-8")).hexdigest()

    con = get_conn_for(str(DB_PATH))
    try:
        n_existentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        ya_mismo_hash = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
    finally:
        con.close()

    if n_existentes:
        result.warnings.append(
            f"Ya existen {n_existentes} fila(s) vigentes para {periodo}. "
            "Si confirmas, se marcarán como reemplazadas y se insertarán las nuevas."
        )

    result.data = {
        "periodo": periodo,
        "fila": fila,
        "file_hash": fhash,
        "ya_ingestado": bool(ya_mismo_hash),
    }
    return result


def commit(texto: str, periodo: str) -> dict:
    """Valida y persiste los datos en la DB.

    Retorna {"status": "ok"|"skipped_duplicate", "run_id": int|None,
             "filas_insertadas": int, "filas_superseded": int}.
    Lanza ValueError si la validación falla.
    """
    result = validate(texto, periodo)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    fila = result.data["fila"]
    fhash = result.data["file_hash"]

    con = get_conn_for(str(DB_PATH))
    try:
        existing_hash_count = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing_hash_count:
            return {"status": "skipped_duplicate", "run_id": None, "filas_insertadas": 0, "filas_superseded": 0}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            """INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status, periodo_declarado)
               VALUES (?,?,?,?,?,?)""",
            ("ingest_mercado_comercio", f"cnc_manual_{periodo}", fhash, now, "running", periodo),
        )
        run_id = cur.lastrowid

        cur2 = con.execute(
            """UPDATE raw_mercado_comercio SET superseded_at=?
               WHERE periodo=? AND superseded_at IS NULL""",
            (now, periodo),
        )
        filas_superseded = cur2.rowcount if cur2.rowcount > 0 else 0

        rows = [
            (periodo, categoria, valor, fhash, idx, run_id)
            for idx, (categoria, valor) in enumerate(fila.items())
        ]
        con.executemany(
            """INSERT INTO raw_mercado_comercio
               (periodo, categoria, variacion_acumulada_pct, file_hash, source_row, ingest_run_id)
               VALUES (?,?,?,?,?,?)""",
            rows,
        )

        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(fila), len(rows), run_id),
        )
        con.commit()
        return {
            "status": "ok",
            "run_id": run_id,
            "filas_insertadas": len(rows),
            "filas_superseded": filas_superseded,
        }
    finally:
        con.close()
