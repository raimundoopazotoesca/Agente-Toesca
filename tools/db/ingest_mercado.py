"""Ingesta de datos de mercado de oficinas (JLL, trimestral) desde texto
copy-paste de la tabla del PDF del informe.

Formato de entrada (una línea por valor, sin tabs):
    Clase
    Inventario (m²)
    ... (10 líneas de encabezado)
    <submercado>
    <clase>
    <9 valores numéricos>
    ... (18 bloques de 11 líneas)

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

PROVEEDORES_VALIDOS = {"JLL"}

_METRIC_KEYS = (
    "inventario_m2",
    "absorcion_trim_m2",
    "absorcion_u12m_m2",
    "vacancia_pct",
    "renta_uf_m2",
    "renta_usd_m2",
    "produccion_trim_m2",
    "produccion_u12m_m2",
    "construccion_m2",
)

EXPECTED_PARES = {
    ("Las Condes (CBD)", "Total"), ("Providencia", "Total"), ("Santiago Centro", "Total"),
    ("Vitacura", "Total"), ("Ciudad empresarial", "Total"), ("Estoril", "Total"), ("Santiago", "Total"),
    ("Las Condes (CBD)", "A"), ("Providencia", "A"), ("Santiago Centro", "A"), ("Santiago", "A"),
    ("Las Condes (CBD)", "B"), ("Providencia", "B"), ("Santiago Centro", "B"),
    ("Vitacura", "B"), ("Ciudad empresarial", "B"), ("Estoril", "B"), ("Santiago", "B"),
}

_CAMPOS_NO_NEGATIVOS = (
    "inventario_m2", "produccion_trim_m2", "produccion_u12m_m2",
    "construccion_m2", "renta_uf_m2", "renta_usd_m2",
)


def _parse_num_cl(raw: str) -> float:
    """Convierte formato numérico chileno a float.

    '1.733.422' -> 1733422.0 (puntos = miles)
    '5,6%'      -> 5.6       (coma = decimal, se descarta el %)
    '-7.786'    -> -7786.0
    """
    s = raw.strip().rstrip("%").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    return float(s)


def parse_tabla_jll(texto: str) -> list[dict]:
    """Parsea el texto copy-paste de la tabla de mercado JLL."""
    lines = [l.strip() for l in texto.strip().splitlines() if l.strip()]
    if lines and lines[0] == "Clase":
        lines = lines[10:]
    if len(lines) % 11 != 0:
        raise ValueError(
            f"Se esperaban bloques de 11 líneas (submercado + clase + 9 métricas), "
            f"quedaron {len(lines)} líneas después del encabezado — revisa el texto pegado."
        )
    filas = []
    for i in range(0, len(lines), 11):
        chunk = lines[i:i + 11]
        submercado, clase = chunk[0], chunk[1]
        valores_raw = chunk[2:11]
        try:
            valores = [_parse_num_cl(v) for v in valores_raw]
        except ValueError as exc:
            raise ValueError(
                f"No se pudo parsear un valor numérico en el bloque de "
                f"'{submercado}' / '{clase}': {exc}"
            ) from exc
        fila = {
            "submercado": submercado,
            "clase": clase,
            "es_total": 1 if submercado == "Santiago" else 0,
        }
        fila.update(dict(zip(_METRIC_KEYS, valores)))
        filas.append(fila)
    return filas


class ValidationResult:
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


def validate(texto: str, periodo: str, proveedor: str = "JLL") -> ValidationResult:
    """Dry-run completo: parsea, valida, arma preview. No escribe en la DB (salvo lecturas)."""
    result = ValidationResult()

    if proveedor not in PROVEEDORES_VALIDOS:
        result.add_error(f"Proveedor {proveedor!r} inválido (válidos: {sorted(PROVEEDORES_VALIDOS)})")
        return result
    if not periodo:
        result.add_error("Falta declarar el período (YYYY-MM) del informe.")
        return result
    if not texto.strip():
        result.add_error("Pega el texto de la tabla antes de validar.")
        return result

    try:
        filas = parse_tabla_jll(texto)
    except ValueError as exc:
        result.add_error(str(exc))
        return result

    pares_encontrados = {(f["submercado"], f["clase"]) for f in filas}
    faltantes = EXPECTED_PARES - pares_encontrados
    sobrantes = pares_encontrados - EXPECTED_PARES
    if faltantes:
        result.add_error(f"Faltan combinaciones submercado/clase: {sorted(faltantes)}")
    if sobrantes:
        result.add_error(f"Combinaciones submercado/clase no reconocidas: {sorted(sobrantes)}")

    for f in filas:
        vac = f.get("vacancia_pct")
        if vac is not None and not (0 <= vac <= 100):
            result.add_error(
                f"{f['submercado']}/{f['clase']}: vacancia_pct fuera de rango 0-100 ({vac})"
            )
        for campo in _CAMPOS_NO_NEGATIVOS:
            valor = f.get(campo)
            if valor is not None and valor < 0:
                result.add_error(
                    f"{f['submercado']}/{f['clase']}: {campo} negativo ({valor}) — valor inesperado"
                )

    if not result.ok:
        return result

    fhash = hashlib.sha256(f"{proveedor}|{periodo}|{texto.strip()}".encode("utf-8")).hexdigest()

    con = get_conn_for(str(DB_PATH))
    try:
        n_existentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas "
            "WHERE periodo=? AND proveedor=? AND superseded_at IS NULL",
            (periodo, proveedor),
        ).fetchone()[0]
        ya_mismo_hash = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
    finally:
        con.close()

    if n_existentes:
        result.warnings.append(
            f"Ya existen {n_existentes} fila(s) vigentes para {periodo}/{proveedor}. "
            "Si confirmas, se marcarán como reemplazadas y se insertarán las nuevas."
        )

    result.data = {
        "periodo": periodo,
        "proveedor": proveedor,
        "filas": filas,
        "n_filas": len(filas),
        "file_hash": fhash,
        "ya_ingestado": bool(ya_mismo_hash),
    }
    return result


def commit(texto: str, periodo: str, proveedor: str = "JLL") -> dict:
    """Re-valida (defensa en profundidad) y persiste. Lanza ValueError si no pasa validación."""
    result = validate(texto, periodo, proveedor)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    filas = result.data["filas"]
    fhash = result.data["file_hash"]
    source_file = f"jll_manual_{periodo}"

    con = get_conn_for(str(DB_PATH))
    try:
        existing_hash_count = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing_hash_count:
            return {"status": "skipped_duplicate", "run_id": None, "filas_insertadas": 0, "filas_superseded": 0}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            """INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status, periodo_declarado)
               VALUES (?,?,?,?,?,?)""",
            ("ingest_mercado", source_file, fhash, now, "running", periodo),
        )
        run_id = cur.lastrowid

        cur2 = con.execute(
            """UPDATE raw_mercado_oficinas SET superseded_at=?
               WHERE periodo=? AND proveedor=? AND superseded_at IS NULL""",
            (now, periodo, proveedor),
        )
        filas_superseded = cur2.rowcount if cur2.rowcount > 0 else 0

        rows = [
            (
                periodo, proveedor, f["submercado"], f["clase"], f["es_total"],
                f["inventario_m2"], f["absorcion_trim_m2"], f["absorcion_u12m_m2"],
                f["vacancia_pct"], f["renta_uf_m2"], f["renta_usd_m2"],
                f["produccion_trim_m2"], f["produccion_u12m_m2"], f["construccion_m2"],
                fhash, idx, run_id,
            )
            for idx, f in enumerate(filas)
        ]
        con.executemany(
            """INSERT INTO raw_mercado_oficinas
               (periodo, proveedor, submercado, clase, es_total,
                inventario_m2, absorcion_trim_m2, absorcion_u12m_m2, vacancia_pct,
                renta_uf_m2, renta_usd_m2, produccion_trim_m2, produccion_u12m_m2,
                construccion_m2, file_hash, source_row, ingest_run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(filas), len(rows), run_id),
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
