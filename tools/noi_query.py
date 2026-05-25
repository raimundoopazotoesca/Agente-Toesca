"""
Consultas y cálculos de NOI sobre la DB del agente.

NOI mensual al 100% por activo vive en derived_kpi (kpi='noi_mensual', UF).
Aquí se agrega por activo / fondo / categoría / total, en 100% y ponderado por
% de participación, y se calculan: anual, anualizado, U12M, variación MoM y YoY.

Anualizado (definición del usuario): para el año pedido, usar los meses que ya
tienen dato real y, para los meses faltantes, el promedio histórico de ese mes
calendario en años anteriores.
"""
from datetime import date

from tools.db.connection import get_conn

_KPI = "noi_mensual"
_RECIPE = "cdg_noi_real_v1"
_SPLIT_RECIPE = "cdg_noi_split_v1"

# Categorías → fuentes (entidad_key, recipe). PT se separa en Torre A (oficinas)
# y Boulevard/CDC (comercial). 'Comercial' = Centros Comerciales + Boulevard.
_CATEGORIA_FUENTE = {
    "Oficinas": [
        ("PT Torre A", _SPLIT_RECIPE), ("Apoquindo", _RECIPE), ("Apo3001", _RECIPE),
    ],
    "Centros Comerciales": [
        ("Viña Centro", _RECIPE), ("Mall Curicó", _RECIPE),
    ],
    "Comercial": [
        ("Viña Centro", _RECIPE), ("Mall Curicó", _RECIPE), ("PT Boulevard", _SPLIT_RECIPE),
    ],
    "Residencias": [("INMOSA", _RECIPE)],
    "Industrial": [("Sucden", _RECIPE)],
}
# Participación a aplicar a las fuentes split (heredan la de PT).
_SPLIT_PART = {"PT Torre A": 0.333, "PT Boulevard": 0.333}


def _activos_meta(conn) -> dict:
    """activo_key → {fondo_key, participacion, categoria} (solo activos con NOI)."""
    out = {}
    for r in conn.execute(
        "SELECT activo_key, fondo_key, participacion, categoria FROM dim_activo"
    ):
        out[r["activo_key"]] = {
            "fondo_key": r["fondo_key"],
            "participacion": r["participacion"] if r["participacion"] is not None else 1.0,
            "categoria": r["categoria"],
        }
    return out


def _noi_activo(conn, activo_key: str, recipe: str = _RECIPE) -> dict:
    """{periodo: valor} NOI mensual al 100% de un activo (o sub-activo)."""
    cur = conn.execute(
        "SELECT periodo, valor FROM derived_kpi WHERE kpi=? AND recipe=? AND "
        "entidad_tipo='activo' AND entidad_key=? ORDER BY periodo",
        (_KPI, recipe, activo_key),
    )
    return {r["periodo"]: r["valor"] for r in cur.fetchall()}


def _activos_de(conn, nivel: str, clave: str | None) -> list[str]:
    meta = _activos_meta(conn)
    con_noi = {a for (a,) in conn.execute(
        "SELECT DISTINCT entidad_key FROM derived_kpi WHERE kpi=? AND entidad_tipo='activo' AND recipe=?",
        (_KPI, _RECIPE),
    )}
    if nivel == "activo":
        return [clave] if clave in con_noi else []
    if nivel == "fondo":
        return [a for a in con_noi if meta.get(a, {}).get("fondo_key") == clave]
    if nivel == "categoria":
        return [a for a in con_noi if meta.get(a, {}).get("categoria") == clave]
    if nivel == "total":
        return sorted(con_noi)
    return []


def serie_mensual(conn, nivel: str, clave: str | None, ponderado: bool = False) -> dict:
    """Serie {periodo: valor} agregada al nivel pedido. ponderado = × participación."""
    meta = _activos_meta(conn)
    acc: dict = {}

    if nivel == "categoria":
        fuentes = _CATEGORIA_FUENTE.get(clave)
        if not fuentes:
            return {}
        for entidad, recipe in fuentes:
            if entidad in _SPLIT_PART:
                factor = _SPLIT_PART[entidad] if ponderado else 1.0
            else:
                factor = meta.get(entidad, {}).get("participacion", 1.0) if ponderado else 1.0
            for per, val in _noi_activo(conn, entidad, recipe).items():
                acc[per] = acc.get(per, 0.0) + val * factor
        return dict(sorted(acc.items()))

    activos = _activos_de(conn, nivel, clave)
    for a in activos:
        factor = meta.get(a, {}).get("participacion", 1.0) if ponderado else 1.0
        for per, val in _noi_activo(conn, a).items():
            acc[per] = acc.get(per, 0.0) + val * factor
    return dict(sorted(acc.items()))


def anual(serie: dict, año: int) -> float:
    return sum(v for p, v in serie.items() if p.startswith(f"{año}-"))


def anualizado(serie: dict, año: int) -> float:
    """YTD real + promedio histórico de cada mes faltante (años anteriores)."""
    hist: dict = {m: [] for m in range(1, 13)}
    for per, val in serie.items():
        y, m = int(per[:4]), int(per[5:7])
        if y < año:
            hist[m].append(val)
    total = 0.0
    for m in range(1, 13):
        per = f"{año}-{m:02d}"
        if per in serie:
            total += serie[per]
        elif hist[m]:
            total += sum(hist[m]) / len(hist[m])
    return total


def u12m(serie: dict, hasta: str | None = None) -> float:
    """Suma de los 12 meses hasta 'hasta' (inclusive). Sin 'hasta' usa el último."""
    if not serie:
        return 0.0
    periodos = sorted(serie)
    if hasta is None:
        hasta = periodos[-1]
    y, m = int(hasta[:4]), int(hasta[5:7])
    meses = set()
    for _ in range(12):
        meses.add(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return sum(serie.get(p, 0.0) for p in meses)


def _prev_periodo(p: str) -> str:
    y, m = int(p[:4]), int(p[5:7])
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    return f"{y}-{m:02d}"


def _yoy_periodo(p: str) -> str:
    return f"{int(p[:4]) - 1}-{p[5:7]}"


def variacion_mom(serie: dict, periodo: str | None = None):
    if not serie:
        return None
    periodos = sorted(serie)
    periodo = periodo or periodos[-1]
    prev = _prev_periodo(periodo)
    if periodo not in serie or prev not in serie or serie[prev] == 0:
        return None
    return (serie[periodo] - serie[prev]) / serie[prev]


def variacion_yoy(serie: dict, periodo: str | None = None):
    if not serie:
        return None
    periodos = sorted(serie)
    periodo = periodo or periodos[-1]
    ant = _yoy_periodo(periodo)
    if periodo not in serie or ant not in serie or serie[ant] == 0:
        return None
    return (serie[periodo] - serie[ant]) / serie[ant]


def consultar_noi(nivel: str, clave: str | None = None,
                  año: int | None = None, ponderado: bool = False) -> str:
    """Resumen de NOI para el agente.

    nivel: 'activo' | 'fondo' | 'categoria' | 'total'
    clave: activo_key / fondo_key / categoría (None para total)
    año:   año de referencia (default: el del último dato)
    ponderado: si True, pondera por % de participación.
    """
    with get_conn() as conn:
        serie = serie_mensual(conn, nivel, clave, ponderado)
    if not serie:
        return (f"Sin NOI en DB para {nivel}"
                + (f" '{clave}'" if clave else "")
                + ". Revisar que el activo/fondo/categoría exista y tenga datos.")

    periodos = sorted(serie)
    ult = periodos[-1]
    año = año or int(ult[:4])
    pond_txt = "ponderado por participación" if ponderado else "100% del activo"

    lines = [f"NOI {nivel}" + (f" '{clave}'" if clave else "") + f" ({pond_txt}) — UF"]
    lines.append(f"  Último mes con dato: {ult} = {serie[ult]:,.1f}")
    mom = variacion_mom(serie, ult)
    yoy = variacion_yoy(serie, ult)
    if mom is not None:
        lines.append(f"  Variación MoM ({_prev_periodo(ult)}→{ult}): {mom*100:+.1f}%")
    if yoy is not None:
        lines.append(f"  Variación YoY ({_yoy_periodo(ult)}→{ult}): {yoy*100:+.1f}%")
    lines.append(f"  NOI {año} (acumulado real): {anual(serie, año):,.1f}")
    lines.append(f"  NOI {año} anualizado (real + prom. histórico meses faltantes): {anualizado(serie, año):,.1f}")
    lines.append(f"  U12M (hasta {ult}): {u12m(serie, ult):,.1f}")
    # últimos 6 meses
    lines.append("  Últimos meses:")
    for p in periodos[-6:]:
        lines.append(f"    {p}: {serie[p]:,.1f}")
    return "\n".join(lines)
