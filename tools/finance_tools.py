"""
Finance indicators wrapper — invokes real-estate-finance-expert skill.

Provides access to compute_or_fetch from the skill for agent.py to calculate
derived financial indicators (rentabilidades, cap rate, dividend yield, TIR, etc).
"""

import json
import sys
from pathlib import Path

# Add skill scripts to path so we can import compute_or_fetch
SKILL_SCRIPTS = Path.home() / ".claude" / "skills" / "real-estate-finance-expert" / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

try:
    from compute_or_fetch import obtener
except ImportError as e:
    obtener = None
    _IMPORT_ERROR = str(e)


def calcular_indicador_financiero(
    kpi: str,
    entidad_tipo: str,
    entidad_key: str,
    periodo: str,
    force_recompute: bool = False,
) -> str:
    """
    Calcula un indicador financiero derivado desde agente_toesca_v2.db.

    Args:
        kpi: Nombre del indicador (ej: "rent_anualizada", "cap_rate_implicito", "dividend_yield")
        entidad_tipo: Tipo de entidad ("serie", "activo", "fondo", etc)
        entidad_key: Identificador único (ej: "CFITOERI1A", "Parque Titanium", "CFITOERI1C")
        periodo: Período en formato YYYY-MM (ej: "2026-03")
        force_recompute: Si True, fuerza recálculo aunque esté en cache

    Returns:
        JSON string con resultado: {valor, unidad, fuente, recipe, persistido, advertencias, metadata}
    """
    if obtener is None:
        return json.dumps({
            "error": True,
            "valor": None,
            "advertencias": [f"Skill no disponible: {_IMPORT_ERROR}"],
            "mensaje": "La skill real-estate-finance-expert no está accesible. Verificar instalación."
        })

    try:
        result = obtener(
            kpi=kpi,
            entidad_tipo=entidad_tipo,
            entidad_key=entidad_key,
            periodo=periodo,
            force_recompute=force_recompute,
        )
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({
            "error": True,
            "valor": None,
            "advertencias": [str(e)],
            "mensaje": f"Error calculando {kpi} para {entidad_key}: {type(e).__name__}"
        })


def calcular_dy_fondo(
    fondo_key: str,
    periodo: str,
    force_recompute: bool = False,
) -> str:
    """
    Calcula DY, DY+Amort y DY contable para todas las series de un fondo en una sola llamada.

    Args:
        fondo_key: "TRI", "PT", "APO"
        periodo: YYYY-MM (ej: "2026-02")
        force_recompute: fuerza recálculo ignorando cache

    Returns:
        JSON con tabla completa: {periodo, filas: [{serie, nemo, dy_bursatil, dy_contable, dy_amort_bursatil, advertencias}]}
    """
    if obtener is None:
        return json.dumps({"error": True, "mensaje": f"Skill no disponible: {_IMPORT_ERROR}"})

    try:
        from tools.db.connection import get_conn
        conn = get_conn()
        series = conn.execute(
            "SELECT nemotecnico FROM dim_serie WHERE fondo_key=? ORDER BY nemotecnico",
            (fondo_key,)
        ).fetchall()
        conn.close()

        if not series:
            return json.dumps({"error": True, "mensaje": f"No se encontraron series para fondo {fondo_key}"})

        filas = []
        for row in series:
            nemo = row[0]
            serie_label = nemo[-1]  # último char: A, C, I

            dy_b = obtener("dividend_yield", "serie", nemo, periodo, force_recompute)
            dy_c = obtener("dividend_yield_contable", "serie", nemo, periodo, force_recompute)
            dy_a = obtener("dividend_yield_con_amort", "serie", nemo, periodo, force_recompute)

            advertencias = []
            for r in [dy_b, dy_c, dy_a]:
                advertencias.extend(r.get("advertencias", []))

            filas.append({
                "serie": serie_label,
                "nemotecnico": nemo,
                "dy_bursatil": dy_b.get("valor"),
                "dy_contable": dy_c.get("valor"),
                "dy_amort_bursatil": dy_a.get("valor"),
                "amort_uf_cuota": dy_a.get("metadata", {}).get("amort_u12m_uf_cuota"),
                "dividendos_uf_cuota": dy_a.get("metadata", {}).get("dividendos_u12m_uf_cuota"),
                "fuente": dy_a.get("fuente"),
                "advertencias": list(set(advertencias)),
            })

        return json.dumps({"fondo": fondo_key, "periodo": periodo, "u12m": True, "filas": filas}, default=str)

    except Exception as e:
        return json.dumps({"error": True, "mensaje": str(e)})


def calcular_tir_fondo(
    fondo_key: str,
    periodo: str,
    force_recompute: bool = False,
) -> str:
    """
    Calcula TIR (XIRR) YTD y U12M para todas las series de un fondo en una sola llamada.

    Variantes calculadas por serie:
      tir_bursatil_ytd   → precio bursátil, T0 = 31-dic año anterior
      tir_contable_ytd   → precio contable, T0 = 31-dic año anterior
      tir_bursatil_u12m  → precio bursátil, T0 = mismo mes año anterior
      tir_contable_u12m  → precio contable, T0 = mismo mes año anterior

    Args:
        fondo_key: 'TRI', 'PT', 'APO'
        periodo:   YYYY-MM (ej: '2025-12')
        force_recompute: fuerza recálculo ignorando cache

    Returns:
        JSON con tabla: {fondo, periodo, filas: [{serie, nemo, tir_bursatil_ytd, tir_contable_ytd,
                          tir_bursatil_u12m, tir_contable_u12m, advertencias}]}
    """
    if obtener is None:
        return json.dumps({"error": True, "mensaje": f"Skill no disponible: {_IMPORT_ERROR}"})

    try:
        from tools.db.connection import get_conn
        conn = get_conn()
        series = conn.execute(
            "SELECT nemotecnico FROM dim_serie WHERE fondo_key=? ORDER BY nemotecnico",
            (fondo_key,)
        ).fetchall()
        conn.close()

        if not series:
            return json.dumps({"error": True, "mensaje": f"No se encontraron series para fondo {fondo_key}"})

        filas = []
        for row in series:
            nemo = row[0]
            serie_label = nemo[-1]

            resultados = {}
            advertencias = []
            for kpi in ("tir_bursatil_desde_inicio", "tir_contable_desde_inicio", "tir_bursatil_ytd", "tir_contable_ytd", "tir_bursatil_u12m", "tir_contable_u12m"):
                r = obtener(kpi, "serie", nemo, periodo, force_recompute)
                resultados[kpi] = r.get("valor")
                advertencias.extend(r.get("advertencias", []))

            filas.append({
                "serie": serie_label,
                "nemotecnico": nemo,
                **resultados,
                "advertencias": list(set(a for a in advertencias if a)),
            })

        return json.dumps({
            "fondo": fondo_key,
            "periodo": periodo,
            "filas": filas,
        }, default=str)

    except Exception as e:
        return json.dumps({"error": True, "mensaje": str(e)})


def listar_indicadores_disponibles() -> str:
    """
    Lista todos los indicadores soportados por la skill.

    Returns:
        JSON string con lista de KPIs, estado, y descripción.
    """
    indicadores = {
        "operativos": [
            {"kpi": "rent_desde_inicio", "descripcion": "Rentabilidad desde primer precio disponible (CAGR)"},
            {"kpi": "rent_anualizada", "descripcion": "Rentabilidad anualizada (CAGR)"},
            {"kpi": "rent_u12m", "descripcion": "Retorno últimos 12 meses (CAGR)"},
            {"kpi": "dividend_yield", "descripcion": "Dividend yield simple (dividendos / precio bursátil)"},
            {"kpi": "dividend_yield_contable", "descripcion": "Dividend yield sobre precio contable"},
            {"kpi": "dividend_yield_capital", "descripcion": "Dividend yield sobre capital suscrito por cuota"},
            {"kpi": "dividend_yield_con_amort", "descripcion": "Dividend yield + amortización de deuda / precio bursátil"},
            {"kpi": "cap_rate_real", "descripcion": "Cap rate real (NOI anual / valor_activo)"},
            {"kpi": "cap_rate_implicito", "descripcion": "Cap rate implícito (NOI anual fondo / market_cap)"},
            {"kpi": "tasa_arriendo_uf_m2", "descripcion": "Tasa de arriendo promedio ponderado UF/m²"},
            {"kpi": "tir_bursatil_ytd",          "descripcion": "TIR XIRR bursátil YTD (T0=31-dic año anterior)"},
            {"kpi": "tir_contable_ytd",          "descripcion": "TIR XIRR contable YTD (T0=31-dic año anterior)"},
            {"kpi": "tir_bursatil_u12m",         "descripcion": "TIR XIRR bursátil últimos 12 meses"},
            {"kpi": "tir_contable_u12m",         "descripcion": "TIR XIRR contable últimos 12 meses"},
            {"kpi": "tir_bursatil_desde_inicio", "descripcion": "TIR bursátil desde primer aporte — XIRR por cuota usando raw_ar_event_line (Aporte/Dividendo/Disminucion + VR Bursátil terminal)"},
        ],
        "pendiente_revision": [
            {"kpi": "tir_contable_desde_inicio", "descripcion": "TIR contable desde inicio — metodología pendiente de definición"},
        ],
        "placeholders": [
            {"kpi": "ltv",  "descripcion": "Loan-to-value", "blocker": "dim_deuda"},
            {"kpi": "dscr", "descripcion": "Debt Service Coverage Ratio", "blocker": "fact_servicio_deuda"},
        ]
    }
    return json.dumps(indicadores)


def invalidar_cache_indicador(kpi: str) -> str:
    """
    Invalida el cache para un indicador específico.
    La próxima consulta lo recalculará.

    Args:
        kpi: Nombre del indicador (ej: "rent_anualizada")

    Returns:
        JSON string con confirmación o error.
    """
    if obtener is None:
        return json.dumps({
            "error": True,
            "mensaje": f"Skill no disponible: {_IMPORT_ERROR}"
        })

    # Nota: invalidation se hace vía CLI en la skill, aquí documentamos cómo
    return json.dumps({
        "status": "OK",
        "mensaje": f"Para invalidar cache de {kpi}, ejecutar: python scripts/compute_or_fetch.py --invalidate {kpi}",
        "ubicacion": str(SKILL_SCRIPTS.parent)
    })


def verificar_skill() -> str:
    """
    Verifica que la skill esté instalada y accesible.

    Returns:
        JSON string con estado.
    """
    if obtener is None:
        return json.dumps({
            "disponible": False,
            "error": _IMPORT_ERROR,
            "skill_path": str(SKILL_SCRIPTS.parent)
        })

    return json.dumps({
        "disponible": True,
        "skill_path": str(SKILL_SCRIPTS.parent),
        "db_path": "agente_toesca_v2.db (en proyecto automation_agent)"
    })
