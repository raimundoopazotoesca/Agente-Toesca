"""Estado de ingesta por tipo de dato (EEFF, Rent Roll, Mercado Oficinas).

Calcula, para cada tipo soportado por el menú de ingesta (web/ingesta.html),
el último período ingestado y el próximo período pendiente, sin cache ni
tabla nueva — se computa on-demand desde las tablas raw_* correspondientes.

No confundir con la lógica de pre-selección de dropdowns en el frontend
(populateEeffTrimestres, etc.): esa es solo una conveniencia de UI y no
calcula correctamente "el período que ya debería estar cargado".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"


def _shift_periodo(periodo: str, meses: int) -> str:
    """Suma (o resta, si meses<0) una cantidad de meses a un período YYYY-MM."""
    year, month = (int(p) for p in periodo.split("-"))
    total = year * 12 + (month - 1) + meses
    year2, month2 = divmod(total, 12)
    return f"{year2:04d}-{month2 + 1:02d}"


def _periodo_en_curso(hoy: date, frecuencia: str) -> str:
    """Período (YYYY-MM) en curso — el mes o trimestre que contiene ``hoy``.

    Para trimestral, es el mes de cierre del trimestre en curso (03/06/09/12),
    esté o no ya cerrado.
    """
    if frecuencia == "mensual":
        return f"{hoy.year:04d}-{hoy.month:02d}"
    if frecuencia == "trimestral":
        quarter_end_month = ((hoy.month - 1) // 3 + 1) * 3
        return f"{hoy.year:04d}-{quarter_end_month:02d}"
    raise ValueError(f"frecuencia inválida: {frecuencia!r}")


def _periodo_cerrado(periodo_en_curso: str, frecuencia: str) -> str:
    """El último período que ya debería estar cerrado y disponible para ingesta."""
    paso = 1 if frecuencia == "mensual" else 3
    return _shift_periodo(periodo_en_curso, -paso)


CONFIG: list[dict] = [
    {
        "id": "eeff",
        "label": "EEFF",
        "frecuencia": "trimestral",
        "tabla": "raw_eeff_line",
        "columna_periodo": "periodo",
        "fondos": ["TRI", "PT", "APO"],
        "columna_fondo": "fondo_key",
        "n_timeline": 4,
        "tab_destino": "eeff",
    },
    {
        "id": "rentroll",
        "label": "Rent Roll",
        "frecuencia": "mensual",
        "tabla": "raw_rent_roll_line",
        "columna_periodo": "periodo",
        "fondos": None,
        "columna_fondo": None,
        "n_timeline": 6,
        "tab_destino": "rentroll",
    },
    {
        "id": "mercado",
        "label": "Mercado Oficinas",
        "frecuencia": "trimestral",
        "tabla": "raw_mercado_oficinas",
        "columna_periodo": "periodo",
        "fondos": None,
        "columna_fondo": None,
        "n_timeline": 4,
        "tab_destino": "mercado",
    },
]


def _periodos_ingestados(con, tipo_cfg: dict) -> dict[str, set[str] | bool]:
    """Para cada período con datos, qué hay: set de fondos (si aplica) o True."""
    tabla = tipo_cfg["tabla"]
    col_periodo = tipo_cfg["columna_periodo"]
    col_fondo = tipo_cfg["columna_fondo"]
    if col_fondo:
        rows = con.execute(
            f"SELECT DISTINCT {col_periodo}, {col_fondo} FROM {tabla} "
            "WHERE superseded_at IS NULL"
        ).fetchall()
        out: dict[str, set[str]] = {}
        for periodo, fondo in rows:
            out.setdefault(periodo, set()).add(fondo)
        return out
    rows = con.execute(
        f"SELECT DISTINCT {col_periodo} FROM {tabla} WHERE superseded_at IS NULL"
    ).fetchall()
    return {periodo: True for (periodo,) in rows}


def _completo(periodo: str, ingestados: dict, tipo_cfg: dict) -> bool:
    valor = ingestados.get(periodo)
    if valor is None:
        return False
    if tipo_cfg["fondos"]:
        return set(tipo_cfg["fondos"]).issubset(valor)
    return bool(valor)


def estado_tipo(con, tipo_cfg: dict, hoy: date) -> dict:
    frecuencia = tipo_cfg["frecuencia"]
    en_curso = _periodo_en_curso(hoy, frecuencia)
    cerrado = _periodo_cerrado(en_curso, frecuencia)

    ingestados = _periodos_ingestados(con, tipo_cfg)
    completos = sorted(p for p in ingestados if _completo(p, ingestados, tipo_cfg))
    ultimo_ingestado = completos[-1] if completos else None

    al_dia = _completo(cerrado, ingestados, tipo_cfg)
    pendiente = None if al_dia else cerrado

    paso = 1 if frecuencia == "mensual" else 3
    n = tipo_cfg["n_timeline"]
    timeline = []
    for i in range(n - 1, -1, -1):
        periodo = _shift_periodo(en_curso, -paso * i)
        if periodo == en_curso:
            estado = "ok" if _completo(periodo, ingestados, tipo_cfg) else "na"
        else:
            estado = "ok" if _completo(periodo, ingestados, tipo_cfg) else "miss"
        timeline.append({"periodo": periodo, "estado": estado})

    return {
        "id": tipo_cfg["id"],
        "label": tipo_cfg["label"],
        "frecuencia": frecuencia,
        "ultimo_ingestado": ultimo_ingestado,
        "pendiente": pendiente,
        "al_dia": al_dia,
        "tab_destino": tipo_cfg["tab_destino"],
        "timeline": timeline,
    }


def estado_ingesta(con, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    return {"tipos": [estado_tipo(con, cfg, hoy) for cfg in CONFIG]}
