"""
Auditoría de cobertura de la DB del agente.
Reporta: qué activos/fondos tienen datos, en qué períodos, y dónde hay gaps mensuales.
"""
from collections import defaultdict
from contextlib import closing, nullcontext

from tools.db.connection import get_conn


def audit_coverage(conn=None) -> dict:
    """Devuelve un dict con cobertura por tabla raw_*."""
    out = {}
    manager = closing(get_conn()) if conn is None else nullcontext(conn)
    with manager as conn:
        for tabla, keycol in [
            ("raw_rent_roll_line", "activo_key"),
            ("raw_er_activo_line", "activo_key"),
            ("raw_flujo_line", "activo_key"),
            ("raw_eeff_line", "fondo_key"),
        ]:
            cur = conn.execute(
                f"SELECT {keycol}, periodo, COUNT(*) FROM {tabla} "
                f"WHERE superseded_at IS NULL GROUP BY {keycol}, periodo"
            )
            por_key = defaultdict(list)
            total = 0
            for k, periodo, n in cur:
                por_key[k].append(periodo)
                total += n
            out[tabla] = {
                "por_clave": {k: sorted(v) for k, v in por_key.items()},
                "total_filas": total,
            }

        for tabla, keycol, datecol, active_filter in [
            ("raw_uf_diaria", None, "fecha", ""),
            ("raw_valor_cuota_contable", "nemotecnico", "fecha", "WHERE superseded_at IS NULL"),
            ("raw_valor_cuota_bursatil", "nemotecnico", "fecha", ""),
            ("raw_dividendo", "nemotecnico", "fecha_pago", "WHERE superseded_at IS NULL"),
            ("derived_kpi", "entidad_key", "periodo", ""),
        ]:
            key_expr = keycol or "'UF'"
            rows = conn.execute(
                f"SELECT {key_expr}, {datecol}, COUNT(*) FROM {tabla} "
                f"{active_filter} GROUP BY {key_expr}, {datecol}"
            ).fetchall()
            por_key = defaultdict(list)
            total = 0
            for key, period, count in rows:
                if period:
                    por_key[key].append(period)
                total += count
            periods = sorted({period for values in por_key.values() for period in values})
            out[tabla] = {
                "por_clave": {key: sorted(values) for key, values in por_key.items()},
                "total_filas": total,
                "desde": periods[0] if periods else None,
                "hasta": periods[-1] if periods else None,
            }
    out["gaps"] = _detect_gaps(out)
    return out


def _detect_gaps(coverage: dict) -> dict:
    gaps = {}
    for tabla, info in coverage.items():
        if tabla not in {"raw_rent_roll_line", "raw_er_activo_line", "raw_flujo_line"}:
            continue
        tabla_gaps = []
        for k, periodos in info.get("por_clave", {}).items():
            if not periodos:
                continue
            # Filtrar periodos con formato YYYY-MM (descartar malformatos)
            periodos_validos = [p for p in periodos if _is_year_month_format(p)]
            if len(periodos_validos) < 2:
                continue
            esperados = _month_range(periodos_validos[0], periodos_validos[-1])
            faltantes = sorted(set(esperados) - set(periodos_validos))
            for p in faltantes:
                tabla_gaps.append({"clave": k, "periodo_faltante": p})
        if tabla_gaps:
            gaps[tabla] = tabla_gaps
    return gaps


def _is_year_month_format(s: str) -> bool:
    """Verifica si el string tiene formato YYYY-MM."""
    if not s:
        return False
    parts = s.split("-")
    return len(parts) == 2


def _month_range(start_ym: str, end_ym: str) -> list[str]:
    """Genera rango de meses YYYY-MM entre dos períodos."""
    parts_start = start_ym.split("-")
    parts_end = end_ym.split("-")
    if len(parts_start) != 2 or len(parts_end) != 2:
        return []
    try:
        y1, m1 = int(parts_start[0]), int(parts_start[1])
        y2, m2 = int(parts_end[0]), int(parts_end[1])
    except ValueError:
        return []
    out = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out
