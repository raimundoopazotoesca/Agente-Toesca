"""
Backfill histórico de la DB del agente (Fase 2).

Recorre los archivos de proveedor ya sincronizados en SharePoint y los ingesta
reusando las MISMAS funciones del flujo en vivo (consistencia garantizada).
Idempotente: reejecutar no duplica (UNIQUE file_hash+source_row).

Uso:
    python -m tools.db.backfill                 # backfill de todo lo disponible
    python -m tools.db.backfill rent_roll       # solo rent rolls
"""
import glob
import os
import re
import sys

from tools.sharepoint_paths import (
    RR_JLL_DIR,
    TRI_VINA_RENT_ROLL_DIR,
    TRI_CURICO_RENT_ROLL_DIR,
)

_MES_NUM = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _periodo_jll(fname: str) -> str | None:
    """'2509 Rent Roll y NOI.xlsx' → '2025-09'."""
    m = re.match(r"(\d{2})(\d{2})\b", os.path.basename(fname))
    if not m:
        return None
    return f"20{m.group(1)}-{m.group(2)}"


def _periodo_tresa(fname: str) -> str | None:
    """'Excel Tres A Viña Marzo 2026.xlsx' → '2026-03'."""
    low = os.path.basename(fname).lower()
    año = None
    ma = re.search(r"(20\d{2})", low)
    if ma:
        año = ma.group(1)
    mes = None
    for nombre, num in _MES_NUM.items():
        if nombre in low:
            mes = num
            break
    if año and mes:
        return f"{año}-{mes:02d}"
    return None


def _listar_xlsx(base_dir: str) -> list[str]:
    if not os.path.isdir(base_dir):
        return []
    out = []
    # Estructura típica: base/{año}/archivo.xlsx ; también base/archivo.xlsx
    out += glob.glob(os.path.join(base_dir, "*.xlsx"))
    out += glob.glob(os.path.join(base_dir, "*", "*.xlsx"))
    # Excluir temporales de Excel (~$...)
    return sorted(p for p in out if not os.path.basename(p).startswith("~$"))


def backfill_rent_roll(verbose: bool = True) -> dict:
    """Backfill de rent rolls JLL + Tres A (Viña/Curicó)."""
    import tools.rentroll_tools as rr

    fuentes = [
        ("jll", RR_JLL_DIR, _periodo_jll),
        ("vina", TRI_VINA_RENT_ROLL_DIR, _periodo_tresa),
        ("curico", TRI_CURICO_RENT_ROLL_DIR, _periodo_tresa),
    ]
    reporte = {"archivos": 0, "filas": 0, "sin_periodo": [], "sin_datos": [], "detalle": []}

    for proveedor, base, parse_periodo in fuentes:
        for path in _listar_xlsx(base):
            periodo = parse_periodo(path)
            bn = os.path.basename(path)
            if not periodo:
                reporte["sin_periodo"].append(bn)
                continue
            try:
                data = rr._read_source_data(path)
            except Exception as e:
                reporte["sin_datos"].append(f"{bn}: {e}")
                continue
            if not data:
                reporte["sin_datos"].append(f"{bn}: hoja 'Rent Roll' vacía o ausente")
                continue
            n = rr._persist_rent_roll(path, periodo, data, proveedor)
            reporte["archivos"] += 1
            reporte["filas"] += n
            reporte["detalle"].append(f"{proveedor} {periodo}: {n} filas <- {bn}")
            if verbose:
                print(f"  [{proveedor}] {periodo}: {n} filas <- {bn}")

    return reporte


def _print_reporte(nombre: str, rep: dict) -> None:
    print(f"\n=== Backfill {nombre} ===")
    print(f"Archivos ingestados: {rep['archivos']}  |  Filas insertadas: {rep['filas']}")
    if rep["sin_periodo"]:
        print(f"Sin período detectable ({len(rep['sin_periodo'])}): {rep['sin_periodo']}")
    if rep["sin_datos"]:
        print(f"Sin datos ({len(rep['sin_datos'])}):")
        for s in rep["sin_datos"]:
            print(f"  - {s}")


def main(argv: list[str]) -> None:
    dominios = argv[1:] or ["rent_roll"]
    if "rent_roll" in dominios:
        rep = backfill_rent_roll(verbose=True)
        _print_reporte("rent_roll", rep)


if __name__ == "__main__":
    main(sys.argv)
