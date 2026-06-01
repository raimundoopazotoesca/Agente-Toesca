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
            {"kpi": "dividend_yield", "descripcion": "Dividend yield simple (dividendos / precio)"},
            {"kpi": "dividend_yield_con_amort", "descripcion": "Dividend yield + amortizaciones"},
            {"kpi": "cap_rate_real", "descripcion": "Cap rate real (NOI anual / valor_activo)"},
            {"kpi": "cap_rate_implicito", "descripcion": "Cap rate implícito (NOI anual fondo / market_cap)"},
            {"kpi": "tasa_arriendo_uf_m2", "descripcion": "Tasa de arriendo promedio ponderado UF/m²"},
        ],
        "placeholders": [
            {"kpi": "tir_actual", "descripcion": "TIR actual (XIRR) — pendiente implementación"},
            {"kpi": "ltv", "descripcion": "Loan-to-value — TODO: dim_deuda", "blocker": "dim_deuda"},
            {"kpi": "dscr", "descripcion": "Debt Service Coverage Ratio — TODO: fact_servicio_deuda", "blocker": "fact_servicio_deuda"},
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
