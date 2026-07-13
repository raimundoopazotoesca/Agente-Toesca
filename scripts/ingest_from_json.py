"""
Ingesta un JSON pre-generado (ej. por ChatGPT) a tablas raw canónicas.

Uso:
  python scripts/ingest_from_json.py --fondo TRI --json <path.json>
  python scripts/ingest_from_json.py --fondo APO --json <path.json> --pdf <path.pdf>
  python scripts/ingest_from_json.py --fondo PT  --json <path.json> --check-only

El JSON puede tener dos secciones:
  - "lineas": líneas contables → raw_eeff_line  (obligatorio)
  - "valor_cuota": valor cuota por serie → raw_valor_cuota_contable  (opcional)
  - "dividendos": dividendos por serie → raw_dividendo  (opcional)
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def _parse_period(value: object, label: str) -> str:
    """Acepta YYYY-MM-DD o YYYY-MM y devuelve YYYY-MM."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} debe ser string no vacío en formato YYYY-MM-DD o YYYY-MM")
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            datetime.strptime(value, fmt)
            return value[:7]
        except ValueError:
            continue
    raise ValueError(f"{label} inválido: {value!r} (esperado YYYY-MM-DD o YYYY-MM)")


def _parse_date(value: object, label: str) -> str:
    """Valida una fecha diaria ISO sin perder el día."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} debe ser string no vacío en formato YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"{label} inválido: {value!r} (esperado YYYY-MM-DD)"
        ) from exc
    return value


def _parse_optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} no puede ser booleano")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError as exc:
            raise ValueError(f"{label} inválido: {value!r}") from exc
    raise ValueError(f"{label} inválido: {value!r}")


def _normalize_eeff_line(line: object, idx: int, periodos_validos: set[str]) -> dict:
    if not isinstance(line, dict):
        raise ValueError(f"lineas[{idx}] debe ser un objeto JSON")

    periodo = _parse_period(line.get("periodo"), f"lineas[{idx}].periodo")
    if periodo not in periodos_validos:
        raise ValueError(
            f"lineas[{idx}].periodo={periodo!r} no aparece en periodos_reportados"
        )

    section = line.get("section")
    if not isinstance(section, str) or not section.strip():
        raise ValueError(f"lineas[{idx}].section debe ser string no vacío")
    section = section.strip()

    cuenta_nombre = line.get("cuenta_nombre")
    if not isinstance(cuenta_nombre, str) or not cuenta_nombre.strip():
        raise ValueError(f"lineas[{idx}].cuenta_nombre debe ser string no vacío")
    cuenta_nombre = cuenta_nombre.strip()

    cuenta_codigo = line.get("cuenta_codigo")
    if cuenta_codigo is not None:
        if not isinstance(cuenta_codigo, str):
            cuenta_codigo = str(cuenta_codigo)
        cuenta_codigo = cuenta_codigo.strip() or None

    monto_clp = _parse_optional_number(line.get("monto_clp"), f"lineas[{idx}].monto_clp")
    monto_uf = _parse_optional_number(line.get("monto_uf"), f"lineas[{idx}].monto_uf")
    if monto_clp is None and monto_uf is None:
        raise ValueError(f"lineas[{idx}] debe tener monto_clp o monto_uf")

    return {
        "section": section,
        "cuenta_codigo": cuenta_codigo,
        "cuenta_nombre": cuenta_nombre,
        "periodo": periodo,
        "monto_clp": monto_clp,
        "monto_uf": monto_uf,
    }


def _validate_eeff_payload(data: dict) -> tuple[list[str], list[dict], int, list[str]]:
    periodos = data.get("periodos_reportados")
    if not isinstance(periodos, list) or not periodos:
        raise ValueError("periodos_reportados debe ser una lista no vacía")

    periodos_norm: list[str] = []
    seen_periodos: set[str] = set()
    for idx, periodo in enumerate(periodos):
        periodo_norm = _parse_period(periodo, f"periodos_reportados[{idx}]")
        if periodo_norm not in seen_periodos:
            seen_periodos.add(periodo_norm)
            periodos_norm.append(periodo_norm)

    lineas = data.get("lineas")
    if not isinstance(lineas, list) or not lineas:
        raise ValueError("lineas debe ser una lista no vacía")

    periodos_added: list[str] = []
    for idx, line in enumerate(lineas):
        if not isinstance(line, dict):
            raise ValueError(f"lineas[{idx}] debe ser un objeto JSON")
        periodo_linea = _parse_period(line.get("periodo"), f"lineas[{idx}].periodo")
        if periodo_linea not in seen_periodos:
            seen_periodos.add(periodo_linea)
            periodos_norm.append(periodo_linea)
            periodos_added.append(periodo_linea)

    lineas_norm: list[dict] = []
    seen_lines: set[tuple] = set()
    duplicates_removed = 0
    for idx, line in enumerate(lineas):
        norm = _normalize_eeff_line(line, idx, seen_periodos)
        dedup_key = (
            norm["section"], norm["cuenta_codigo"], norm["cuenta_nombre"],
            norm["periodo"], norm["monto_clp"], norm["monto_uf"],
        )
        if dedup_key in seen_lines:
            duplicates_removed += 1
            continue
        seen_lines.add(dedup_key)
        lineas_norm.append(norm)

    if not lineas_norm:
        raise ValueError("Todas las líneas quedaron vacías o duplicadas tras validar")

    return periodos_norm, lineas_norm, duplicates_removed, periodos_added


def _normalize_dividendo(div: object, idx: int) -> dict:
    if not isinstance(div, dict):
        raise ValueError(f"dividendos[{idx}] debe ser un objeto JSON")

    fecha_pago = _parse_date(div.get("fecha_pago"), f"dividendos[{idx}].fecha_pago")

    nemotecnico = div.get("nemotecnico")
    if not isinstance(nemotecnico, str) or not nemotecnico.strip():
        raise ValueError(f"dividendos[{idx}].nemotecnico debe ser string no vacío")

    monto_uf_cuota = _parse_optional_number(div.get("monto_uf_cuota"), f"dividendos[{idx}].monto_uf_cuota")
    monto_clp_cuota = _parse_optional_number(div.get("monto_clp_cuota"), f"dividendos[{idx}].monto_clp_cuota")

    if monto_uf_cuota is None and monto_clp_cuota is None:
        raise ValueError(f"dividendos[{idx}] debe tener monto_uf_cuota o monto_clp_cuota")

    return {
        "fecha_pago": fecha_pago,
        "nemotecnico": nemotecnico.strip(),
        "monto_uf_cuota": monto_uf_cuota,
        "monto_clp_cuota": monto_clp_cuota,
        "periodo": fecha_pago[:7],
    }


def _normalize_valor_cuota(vc: object, idx: int) -> dict:
    if not isinstance(vc, dict):
        raise ValueError(f"valor_cuota[{idx}] debe ser un objeto JSON")

    fecha = _parse_date(vc.get("fecha"), f"valor_cuota[{idx}].fecha")

    nemotecnico = vc.get("nemotecnico")
    if not isinstance(nemotecnico, str) or not nemotecnico.strip():
        raise ValueError(f"valor_cuota[{idx}].nemotecnico debe ser string no vacío")

    cuotas = _parse_optional_number(vc.get("cuotas"), f"valor_cuota[{idx}].cuotas")
    precio_clp = _parse_optional_number(vc.get("precio_clp"), f"valor_cuota[{idx}].precio_clp")
    precio_uf = _parse_optional_number(vc.get("precio_uf"), f"valor_cuota[{idx}].precio_uf")
    uf_dia = _parse_optional_number(vc.get("uf_dia"), f"valor_cuota[{idx}].uf_dia")

    if precio_clp is None and precio_uf is None:
        raise ValueError(f"valor_cuota[{idx}] debe tener precio_clp o precio_uf")

    return {
        "fecha": fecha,
        "nemotecnico": nemotecnico.strip(),
        "cuotas": cuotas,
        "precio_clp": precio_clp,
        "precio_uf": precio_uf,
        "uf_dia": uf_dia,
        "periodo": fecha[:7],  # YYYY-MM
    }


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fondo", required=True, choices=["TRI", "PT", "APO"])
    ap.add_argument("--json", required=True, help="ruta al JSON generado externamente")
    ap.add_argument("--pdf", help="ruta al PDF original (para file_hash); si no se da, usa el JSON como source")
    ap.add_argument("--check-only", action="store_true", help="solo valida el JSON; no inserta en DB")
    args = ap.parse_args()

    json_path = Path(args.json)
    data = json.loads(json_path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("El JSON raíz debe ser un objeto")

    # --- Validar sección lineas ---
    periodos, lineas, duplicates_removed, periodos_added = _validate_eeff_payload(data)
    print(f"EEFF: {len(lineas)} líneas, periodos: {periodos}, duplicados removidos: {duplicates_removed}")
    if periodos_added:
        print(f"  Periodos agregados desde lineas: {periodos_added}")

    # --- Validar sección valor_cuota (opcional) ---
    vc_raw = data.get("valor_cuota", [])
    vc_norm: list[dict] = []
    if vc_raw:
        if not isinstance(vc_raw, list):
            raise ValueError("valor_cuota debe ser una lista")
        for idx, vc in enumerate(vc_raw):
            vc_norm.append(_normalize_valor_cuota(vc, idx))
        print(f"Valor cuota: {len(vc_norm)} entradas ({[v['nemotecnico'] + '@' + v['fecha'] for v in vc_norm]})")
    else:
        print("Valor cuota: no incluido en este JSON")

    # --- Validar sección dividendos (opcional) ---
    div_raw = data.get("dividendos", [])
    div_norm: list[dict] = []
    if div_raw:
        if not isinstance(div_raw, list):
            raise ValueError("dividendos debe ser una lista")
        for idx, div in enumerate(div_raw):
            div_norm.append(_normalize_dividendo(div, idx))
        print(f"Dividendos: {len(div_norm)} entradas ({[d['nemotecnico'] + '@' + d['fecha_pago'] for d in div_norm]})")
    else:
        print("Dividendos: no incluido en este JSON")

    # file_hash: preferir PDF original, sino hash del JSON
    source_ref = json_path
    if args.pdf:
        source_ref = Path(args.pdf)
    fhash = hashlib.sha256(source_ref.read_bytes()).hexdigest()
    source_file = source_ref.name

    if args.check_only:
        print(f"Check OK. source_file={source_file} file_hash={fhash}")
        return

    con = sqlite3.connect(DB_PATH)
    try:
        # --- Insertar raw_eeff_line ---
        existing_eeff = con.execute(
            "SELECT COUNT(*) FROM raw_eeff_line WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing_eeff > 0:
            print(f"EEFF ya ingresado ({existing_eeff} filas con este hash), saltando raw_eeff_line.")
        else:
            cur = con.execute(
                "INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status) VALUES (?,?,?,?,?)",
                ("ingest_from_json", source_file, fhash,
                 datetime.now().isoformat(timespec="seconds"), "running"),
            )
            run_id = cur.lastrowid

            rows_eeff = [
                (args.fondo, L["periodo"], L["cuenta_codigo"], L["cuenta_nombre"],
                 L["monto_clp"], L["monto_uf"], source_file, L["section"], None, fhash, run_id)
                for L in lineas
            ]
            con.executemany(
                """INSERT INTO raw_eeff_line
                   (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
                    source_file, source_sheet, source_row, file_hash, ingest_run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                rows_eeff,
            )
            con.execute(
                "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
                ("ok", datetime.now().isoformat(timespec="seconds"), len(lineas), len(rows_eeff), run_id),
            )
            print(f"raw_eeff_line: {len(rows_eeff)} filas insertadas OK")

        # --- Insertar raw_valor_cuota_contable ---
        if vc_norm:
            inserted_vc = 0
            skipped_vc = 0
            for vc in vc_norm:
                try:
                    con.execute(
                        """INSERT OR IGNORE INTO raw_valor_cuota_contable
                           (fondo_key, nemotecnico, fecha, precio_clp, precio_uf,
                            uf_dia, cuotas, periodo, source_file, file_hash)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (args.fondo, vc["nemotecnico"], vc["fecha"],
                         vc["precio_clp"], vc["precio_uf"], vc["uf_dia"],
                         vc["cuotas"], vc["periodo"], source_file, fhash),
                    )
                    if con.execute("SELECT changes()").fetchone()[0] > 0:
                        inserted_vc += 1
                    else:
                        skipped_vc += 1
                except Exception as e:
                    print(f"  WARN valor_cuota {vc['nemotecnico']}@{vc['fecha']}: {e}")
            print(f"raw_valor_cuota_contable: {inserted_vc} insertadas, {skipped_vc} ya existían")

        # --- Insertar raw_dividendo ---
        if div_norm:
            inserted_div = 0
            skipped_div = 0
            for div in div_norm:
                try:
                    con.execute(
                        """INSERT INTO raw_dividendo
                           (fondo_key, nemotecnico, fecha_pago, monto_uf_cuota, monto_clp_cuota,
                            periodo, source_file, file_hash, tipo)
                           SELECT ?,?,?,?,?,?,?,?,'dividendo'
                           WHERE NOT EXISTS (
                               SELECT 1 FROM raw_dividendo
                               WHERE fondo_key = ? AND nemotecnico = ?
                                 AND fecha_pago = ? AND tipo = 'dividendo'
                                 AND source_file = ? AND file_hash = ?
                                 AND superseded_at IS NULL
                           )""",
                        (
                            args.fondo, div["nemotecnico"], div["fecha_pago"],
                            div["monto_uf_cuota"], div["monto_clp_cuota"],
                            div["periodo"], source_file, fhash,
                            args.fondo, div["nemotecnico"], div["fecha_pago"],
                            source_file, fhash,
                        ),
                    )
                    if con.execute("SELECT changes()").fetchone()[0] > 0:
                        inserted_div += 1
                    else:
                        skipped_div += 1
                except Exception as e:
                    print(f"  WARN dividendo {div['nemotecnico']}@{div['fecha_pago']}: {e}")
            print(f"raw_dividendo: {inserted_div} insertadas, {skipped_div} ya existían")

        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    main()
