"""Estado de ingesta por tipo de dato (EEFF, Rent Roll, Mercado, etc.).

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
        "columna_sub_ingesta": "fondo_key",
        "n_timeline": 4,
        "tab_destino": "eeff",
        "sub_ingestas": [
            {"key": "TRI", "label": "TRI", "valores": ["TRI"]},
            {"key": "PT", "label": "PT", "valores": ["PT"]},
            {"key": "APO", "label": "APO", "valores": ["APO"]},
        ],
    },
    {
        "id": "rentroll",
        "label": "Rent Roll",
        "frecuencia": "mensual",
        "tabla": "raw_rent_roll_line",
        "columna_periodo": "periodo",
        # completo == los 3 proveedores completos (unión de sus activo_key);
        # si falta uno solo (p.ej. JLL) el período entero queda "pendiente"
        "fondos": ["PT", "Apoquindo", "Apo3001", "Viña Centro", "Mall Curicó"],
        "columna_fondo": "activo_key",
        # sub-ingestas: agrupan activo_key por proveedor (JLL entrega 3 activos
        # en un solo archivo; Tres Asociados entrega Viña y Curicó por separado)
        "columna_sub_ingesta": "activo_key",
        "n_timeline": 6,
        "tab_destino": "rentroll",
        "sub_ingestas": [
            {"key": "jll", "label": "JLL (PT, Apo, Apo3001)", "valores": ["PT", "Apoquindo", "Apo3001"]},
            {"key": "tresa_vina", "label": "Tres A · Viña", "valores": ["Viña Centro"]},
            {"key": "tresa_curico", "label": "Tres A · Curicó", "valores": ["Mall Curicó"]},
        ],
    },
    {
        "id": "mercado",
        "label": "Mercado Oficinas",
        "frecuencia": "trimestral",
        "tabla": "raw_mercado_oficinas",
        "columna_periodo": "periodo",
        "fondos": None,
        "columna_fondo": None,
        "columna_sub_ingesta": None,
        "n_timeline": 4,
        "tab_destino": "mercado",
        "sub_ingestas": [],
    },
    {
        "id": "balance",
        "label": "Balance Consolidado",
        "frecuencia": "trimestral",
        "tabla": "raw_balance_consolidado_line",
        "columna_periodo": "periodo",
        "fondos": ["TRI", "PT", "Apo"],
        "columna_fondo": "fondo_key",
        "columna_sub_ingesta": "fondo_key",
        "n_timeline": 4,
        "tab_destino": "balance",
        "sub_ingestas": [
            {"key": "TRI", "label": "TRI", "valores": ["TRI"]},
            {"key": "PT", "label": "PT", "valores": ["PT"]},
            {"key": "Apo", "label": "Apo", "valores": ["Apo"]},
        ],
    },
    {
        "id": "parking_pt",
        "label": "Parking PT",
        "frecuencia": "mensual",
        "tabla": "raw_parking_ingreso_line",
        "columna_periodo": "periodo",
        "fondos": None,
        "columna_fondo": None,
        "columna_sub_ingesta": None,
        "n_timeline": 6,
        "tab_destino": "parking",
        "sub_ingestas": [],
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


def _periodos_por_valor(con, tabla: str, col_periodo: str, col_valor: str) -> dict[str, set[str]]:
    """Para cada período, qué valores distintos de ``col_valor`` hay (p.ej. fondo o activo)."""
    rows = con.execute(
        f"SELECT DISTINCT {col_periodo}, {col_valor} FROM {tabla} WHERE superseded_at IS NULL"
    ).fetchall()
    out: dict[str, set[str]] = {}
    for periodo, valor in rows:
        out.setdefault(periodo, set()).add(valor)
    return out


def _valores_completo(periodo: str, ingestados_sub: dict[str, set[str]], valores: list[str]) -> bool:
    presentes = ingestados_sub.get(periodo)
    if presentes is None:
        return False
    return set(valores).issubset(presentes)


def _clasifica(periodo: str, en_curso: str, completo: bool) -> str:
    """ok = completo · miss = período cerrado sin ingestar · na = en curso o futuro."""
    if periodo > en_curso:
        return "na"
    if periodo == en_curso:
        return "ok" if completo else "na"
    return "ok" if completo else "miss"


def _construir_timeline(en_curso: str, frecuencia: str, n: int, offset: int, completo_fn) -> list[dict]:
    """Timeline de ``n`` períodos terminando en ``en_curso`` desplazado ``offset`` pasos
    (offset<0: ventana hacia el pasado, offset>0: hacia el futuro)."""
    paso = 1 if frecuencia == "mensual" else 3
    ancla = _shift_periodo(en_curso, offset * paso)
    timeline = []
    for i in range(n - 1, -1, -1):
        periodo = _shift_periodo(ancla, -paso * i)
        timeline.append({"periodo": periodo, "estado": _clasifica(periodo, en_curso, completo_fn(periodo))})
    return timeline


def _estado_sub(
    sub_cfg: dict, ingestados_sub: dict[str, set[str]], en_curso: str, cerrado: str,
    frecuencia: str, n: int,
) -> dict:
    valores = sub_cfg["valores"]
    completos = sorted(p for p in ingestados_sub if _valores_completo(p, ingestados_sub, valores))
    ultimo_ingestado = completos[-1] if completos else None

    al_dia = _valores_completo(cerrado, ingestados_sub, valores)
    pendiente = None if al_dia else cerrado

    timeline = _construir_timeline(
        en_curso, frecuencia, n, 0, lambda p: _valores_completo(p, ingestados_sub, valores)
    )

    return {
        "key": sub_cfg["key"],
        "label": sub_cfg["label"],
        "ultimo_ingestado": ultimo_ingestado,
        "pendiente": pendiente,
        "al_dia": al_dia,
        "timeline": timeline,
    }


def estado_tipo(con, tipo_cfg: dict, hoy: date) -> dict:
    frecuencia = tipo_cfg["frecuencia"]
    en_curso = _periodo_en_curso(hoy, frecuencia)
    cerrado = _periodo_cerrado(en_curso, frecuencia)
    n = tipo_cfg["n_timeline"]

    ingestados = _periodos_ingestados(con, tipo_cfg)
    completos = sorted(p for p in ingestados if _completo(p, ingestados, tipo_cfg))
    ultimo_ingestado = completos[-1] if completos else None

    al_dia = _completo(cerrado, ingestados, tipo_cfg)
    pendiente = None if al_dia else cerrado

    timeline = _construir_timeline(en_curso, frecuencia, n, 0, lambda p: _completo(p, ingestados, tipo_cfg))

    sub_ingestas_cfg = tipo_cfg.get("sub_ingestas") or []
    if sub_ingestas_cfg:
        ingestados_sub = _periodos_por_valor(
            con, tipo_cfg["tabla"], tipo_cfg["columna_periodo"], tipo_cfg["columna_sub_ingesta"]
        )
        subs = [
            _estado_sub(s, ingestados_sub, en_curso, cerrado, frecuencia, n)
            for s in sub_ingestas_cfg
        ]
    else:
        subs = []

    resumen = {"al_dia": sum(1 for s in subs if s["al_dia"]), "total": len(subs)} if subs else None

    return {
        "id": tipo_cfg["id"],
        "label": tipo_cfg["label"],
        "frecuencia": frecuencia,
        "ultimo_ingestado": ultimo_ingestado,
        "pendiente": pendiente,
        "al_dia": al_dia,
        "tab_destino": tipo_cfg["tab_destino"],
        "timeline": timeline,
        "sub_ingestas": subs,
        "resumen": resumen,
    }


_BURSATIL_NEMOTECNICOS = ["CFITRIPT-E", "CFITOERI1A", "CFITOERI1C", "CFITOERI1I"]


def estado_uf(con, hoy: date) -> dict:
    """Estado de la ingesta diaria de UF (raw_uf_diaria, vía API CMF/SII).

    La UF de todo el mes en curso se publica de antemano (BCCh/SII la fija
    con anticipación), por lo que "al día" no se mide en días de atraso
    respecto de hoy, sino igual que una ingesta mensual: basta con tener
    algún valor cargado del mes cerrado (el mes anterior) o más reciente.
    """
    row = con.execute(
        "SELECT fecha, valor, fuente FROM raw_uf_diaria ORDER BY fecha DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {
            "id": "uf", "label": "UF", "ultima_fecha": None, "ultimo_valor": None,
            "dias_atraso": None, "estado": "miss", "fuente": None,
        }
    ultima_fecha, ultimo_valor, fuente = row
    dias_atraso = (hoy - date.fromisoformat(ultima_fecha)).days
    en_curso = _periodo_en_curso(hoy, "mensual")
    cerrado = _periodo_cerrado(en_curso, "mensual")
    ultimo_periodo = ultima_fecha[:7]
    if ultimo_periodo >= cerrado:
        estado = "ok"
    elif ultimo_periodo == _shift_periodo(cerrado, -1):
        estado = "warn"
    else:
        estado = "miss"
    return {
        "id": "uf", "label": "UF", "ultima_fecha": ultima_fecha, "ultimo_valor": ultimo_valor,
        "dias_atraso": dias_atraso, "estado": estado, "fuente": fuente,
    }


def estado_bursatil(con, hoy: date) -> dict:
    """Estado de la ingesta mensual de valor cuota bursátil (mercado en línea)."""
    en_curso = _periodo_en_curso(hoy, "mensual")
    cerrado = _periodo_cerrado(en_curso, "mensual")
    placeholders = ",".join("?" * len(_BURSATIL_NEMOTECNICOS))
    rows = con.execute(
        f"SELECT r.nemotecnico, r.fecha, r.precio_clp, r.fuente, s.fondo_key, s.serie "
        f"FROM raw_valor_cuota_bursatil r "
        f"JOIN (SELECT nemotecnico, MAX(fecha) AS fecha FROM raw_valor_cuota_bursatil "
        f"WHERE nemotecnico IN ({placeholders}) GROUP BY nemotecnico) m "
        f"ON m.nemotecnico = r.nemotecnico AND m.fecha = r.fecha "
        f"LEFT JOIN dim_serie s ON s.nemotecnico = r.nemotecnico",
        _BURSATIL_NEMOTECNICOS,
    ).fetchall()
    valores = [
        {"nemotecnico": n, "fecha": f, "precio_clp": v, "fuente": fuente, "fondo": fondo, "serie": serie}
        for n, f, v, fuente, fondo, serie in rows
    ]
    ultimas_fechas = {v["nemotecnico"]: v["fecha"] for v in valores}
    ultima_fecha = max((f for f in ultimas_fechas.values() if f), default=None)
    al_dia = len(ultimas_fechas) == len(_BURSATIL_NEMOTECNICOS) and all(
        ultimas_fechas[n][:7] >= cerrado for n in _BURSATIL_NEMOTECNICOS
    )
    fuentes = sorted({v["fuente"] for v in valores if v["fuente"]})
    return {
        "id": "bursatil",
        "label": "Valor cuota bursátil",
        "ultima_fecha": ultima_fecha,
        "valores": valores,
        "fuente": ", ".join(fuentes) if fuentes else None,
        "pendiente": None if al_dia else cerrado,
        "al_dia": al_dia,
        "estado": "ok" if al_dia else "miss",
    }


def estado_ingesta(con, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    return {
        "tipos": [estado_tipo(con, cfg, hoy) for cfg in CONFIG],
        "uf": estado_uf(con, hoy),
        "bursatil": estado_bursatil(con, hoy),
    }


def _periodos_consecutivos(inicio: str, frecuencia: str, total: int) -> list[str]:
    paso = 1 if frecuencia == "mensual" else 3
    return [_shift_periodo(inicio, i * paso) for i in range(total)]


def timeline_rango(con, tipo_id: str, hoy: date, offset_min: int, offset_max: int) -> dict:
    """Devuelve, en un solo cálculo, TODOS los períodos navegables por las flechas
    del frontend (de offset_min a offset_max), para que la UI pueda cachear el
    rango completo y deslizar la ventana de ``n_timeline`` períodos sin más
    llamadas al servidor. No recalcula ultimo_ingestado/pendiente/al_dia,
    que siempre reflejan hoy (esos vienen de /api/estado_ingesta)."""
    tipo_cfg = next(c for c in CONFIG if c["id"] == tipo_id)
    frecuencia = tipo_cfg["frecuencia"]
    en_curso = _periodo_en_curso(hoy, frecuencia)
    n = tipo_cfg["n_timeline"]
    paso = 1 if frecuencia == "mensual" else 3

    total = offset_max - offset_min + n
    inicio = _shift_periodo(en_curso, (offset_min - (n - 1)) * paso)
    periodos = _periodos_consecutivos(inicio, frecuencia, total)

    ingestados = _periodos_ingestados(con, tipo_cfg)
    principal = [
        {"periodo": p, "estado": _clasifica(p, en_curso, _completo(p, ingestados, tipo_cfg))}
        for p in periodos
    ]

    sub_ingestas_cfg = tipo_cfg.get("sub_ingestas") or []
    subs = []
    if sub_ingestas_cfg:
        ingestados_sub = _periodos_por_valor(
            con, tipo_cfg["tabla"], tipo_cfg["columna_periodo"], tipo_cfg["columna_sub_ingesta"]
        )
        for s in sub_ingestas_cfg:
            valores = s["valores"]
            sub_periodos = [
                {"periodo": p, "estado": _clasifica(p, en_curso, _valores_completo(p, ingestados_sub, valores))}
                for p in periodos
            ]
            subs.append({"key": s["key"], "label": s["label"], "periodos": sub_periodos})

    return {
        "id": tipo_cfg["id"],
        "n": n,
        "offset_min": offset_min,
        "offset_max": offset_max,
        "periodos": principal,
        "sub_ingestas": subs,
    }
