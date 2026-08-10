"""Ingesta de datos de mercado de bodegas (GPS Property, semestral) desde
texto copy-paste de la tabla del informe.

Formato de entrada esperado (una línea por zona, tokens separados por
espacio, "-" como null):

    Centro A/B - 289.789 4,6% 1.340 0,5% - -1.340 0,226 9,21

Columnas en orden: zona(+), clase, producción, inventario_final,
participación%, vacancia_actual, tasa_vacancia%, vacancia_anterior,
absorción, precio_uf, precio_usd. La fila "Gran Santiago" no lleva clase
(9 valores en vez de 10 tokens de datos) y es el total.

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

ZONAS_ESPERADAS = {"Centro", "Nor-Poniente", "Norte", "Poniente", "Sur", "Gran Santiago"}
ZONA_TOTAL = "Gran Santiago"

_METRIC_KEYS = (
    "produccion_m2", "inventario_final_m2", "participacion_pct",
    "vacancia_actual_m2", "tasa_vacancia_pct", "vacancia_anterior_m2",
    "absorcion_m2", "precio_uf_m2", "precio_usd_m2",
)

_CAMPOS_NO_NEGATIVOS = (
    "produccion_m2", "inventario_final_m2", "participacion_pct",
    "vacancia_actual_m2", "vacancia_anterior_m2", "precio_uf_m2", "precio_usd_m2",
)


def _parse_num_cl(raw: str) -> float | None:
    """Convierte formato numérico chileno a float, o None si es '-'.

    '289.789'   -> 289789.0 (puntos = miles)
    '4,6%'      -> 4.6      (coma = decimal, se descarta el %)
    '0,5%'      -> 0.5
    '-'         -> None
    """
    s = raw.strip().rstrip("%").strip()
    if s == "-":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    return float(s)


def _is_valor_token(tok: str) -> bool:
    """Verifica si el token es un valor válido (número o "-")."""
    return tok == "-" or _looks_numeric(tok)


def _looks_numeric(tok: str) -> bool:
    """Verifica si un token se ve como número."""
    s = tok.rstrip("%")
    s = s.replace(".", "").replace(",", ".")
    try:
        float(s)
        return True
    except ValueError:
        return False


def parse_tabla_bodegas(texto: str) -> list[dict]:
    """Parsea el texto copy-paste de la tabla de mercado bodegas (GPS Property).

    Ignora líneas de encabezado (no calzan el patrón zona + 9 valores).
    Retorna una lista de dicts con claves: zona, clase, es_total, y 9 métricas.
    """
    lines = [l.strip() for l in texto.strip().splitlines() if l.strip()]
    filas: list[dict] = []
    for line in lines:
        tokens = line.split()
        if len(tokens) < 10:
            continue
        # Última fila (Gran Santiago) no tiene columna "clase": 9 valores + zona(s).
        # Filas de zona sí tienen "clase" = "A/B": zona(s) + clase + 9 valores.
        valores_9 = tokens[-9:]
        if not all(_is_valor_token(t) for t in valores_9):
            continue
        resto = tokens[:-9]
        if resto and resto[-1] == "A/B":
            zona = " ".join(resto[:-1])
            clase = "A/B"
            es_total = 0
        else:
            zona = " ".join(resto)
            clase = None
            es_total = 1
        if zona not in ZONAS_ESPERADAS:
            continue
        valores = [_parse_num_cl(v) for v in valores_9]
        fila = {"zona": zona, "clase": clase, "es_total": es_total}
        fila.update(dict(zip(_METRIC_KEYS, valores)))
        filas.append(fila)
    return filas


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
    """Valida que el texto contenga todas las zonas esperadas y sin errores de datos.

    Retorna ValidationResult con ok=True/False, errores, warnings, y datos parseados.
    """
    result = ValidationResult()

    if not periodo:
        result.add_error("Falta declarar el período (YYYY-MM) del informe.")
        return result
    if not texto.strip():
        result.add_error("Pega el texto de la tabla antes de validar.")
        return result

    filas = parse_tabla_bodegas(texto)
    if not filas:
        result.add_error(
            "No se detectaron filas válidas — revisa que el texto pegado tenga el "
            "formato 'Zona [A/B] <9 valores numéricos o -> ' por línea."
        )
        return result

    zonas_encontradas = {f["zona"] for f in filas}
    faltantes = ZONAS_ESPERADAS - zonas_encontradas
    sobrantes = zonas_encontradas - ZONAS_ESPERADAS
    if faltantes:
        result.add_error(f"Faltan zonas: {sorted(faltantes)}")
    if sobrantes:
        result.add_error(f"Zonas no reconocidas: {sorted(sobrantes)}")

    for f in filas:
        tasa = f.get("tasa_vacancia_pct")
        if tasa is not None and not (0 <= tasa <= 100):
            result.add_error(f"{f['zona']}: tasa_vacancia_pct fuera de rango 0-100 ({tasa})")
        for campo in _CAMPOS_NO_NEGATIVOS:
            valor = f.get(campo)
            if valor is not None and valor < 0:
                result.add_error(f"{f['zona']}: {campo} negativo ({valor}) — valor inesperado")

    if not result.ok:
        return result

    fhash = hashlib.sha256(f"{periodo}|{texto.strip()}".encode("utf-8")).hexdigest()

    con = get_conn_for(str(DB_PATH))
    try:
        n_existentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        ya_mismo_hash = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE file_hash=?", (fhash,)
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
        "filas": filas,
        "n_filas": len(filas),
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

    filas = result.data["filas"]
    fhash = result.data["file_hash"]
    source_file = f"gps_manual_{periodo}"

    con = get_conn_for(str(DB_PATH))
    try:
        existing_hash_count = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing_hash_count:
            return {"status": "skipped_duplicate", "run_id": None, "filas_insertadas": 0, "filas_superseded": 0}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            """INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status, periodo_declarado)
               VALUES (?,?,?,?,?,?)""",
            ("ingest_mercado_bodegas", source_file, fhash, now, "running", periodo),
        )
        run_id = cur.lastrowid

        cur2 = con.execute(
            """UPDATE raw_mercado_bodegas SET superseded_at=?
               WHERE periodo=? AND superseded_at IS NULL""",
            (now, periodo),
        )
        filas_superseded = cur2.rowcount if cur2.rowcount > 0 else 0

        rows = [
            (
                periodo, f["zona"], f["clase"], f["es_total"],
                f["produccion_m2"], f["inventario_final_m2"], f["participacion_pct"],
                f["vacancia_actual_m2"], f["tasa_vacancia_pct"], f["vacancia_anterior_m2"],
                f["absorcion_m2"], f["precio_uf_m2"], f["precio_usd_m2"],
                fhash, idx, run_id,
            )
            for idx, f in enumerate(filas)
        ]
        con.executemany(
            """INSERT INTO raw_mercado_bodegas
               (periodo, zona, clase, es_total, produccion_m2, inventario_final_m2,
                participacion_pct, vacancia_actual_m2, tasa_vacancia_pct,
                vacancia_anterior_m2, absorcion_m2, precio_uf_m2, precio_usd_m2,
                file_hash, source_row, ingest_run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
