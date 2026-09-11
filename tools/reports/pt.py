"""Read-only, consolidated report for PT (Torre A + Inmob. Boulevard PT SpA).

A diferencia de Apoquindos, acá NO hay silueta de edificio ni layout de
locales: el fact sheet de PT usa donas por arrendatario en vez de desglose
por edificio (ver FONDOS_CFG["PT"]["page3"] en scripts/build_factsheet.py,
sin clave "edificios") — nunca se trazaron coordenadas de piso/local para
Torre A ni Inmob. CdC, así que esta vista no las inventa. Muestra métricas
agregadas por edificio (ocupación, vacancia, GLA, renta) + el mismo análisis
consolidado con selector de scope y drill-down por arrendatario que
Apoquindos, reutilizando exactamente las mismas funciones de
tools/db/rent_roll_stats.py."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.db.rent_roll_stats import (
    get_rubro_arrendatario, get_tipo_activo, get_perfil_vencimiento, get_unidades, get_plano_locales,
)
from tools.reports.apoquindos import _consolidar_por_arrendatario, _agrupar_categoria


_ASSETS = (("Torre A", "Torre A S.A."), ("Boulevard", "Inmob. Boulevard PT SpA"))

# Mismo plano y coordenadas que scripts/build_factsheet.py::FONDOS_CFG["PT"]
# ["page4"]["plano"] (trazado a mano por el usuario sobre el plano real de
# Local 100, Inmob. CdC) — copiado acá como datos puros en vez de importar
# build_factsheet.py entero (que ejecuta trabajo pesado a nivel de módulo,
# como leer y codificar las imágenes, solo por definir FONDOS_CFG). Las
# imágenes se sirven como archivos estáticos (ver scripts/ingesta_server.py),
# no embebidas en el JSON. Formas "x/y/w/h" se normalizan a polígono acá
# mismo para que el frontend solo tenga que dibujar un tipo de forma.
_PLANO_LOCAL_100_EDIFICIO = "Inmob. CdC"
_PLANO_LOCAL_100_PISOS = [
    {
        "nombre": "Piso -1", "imagen": "pt_plano_piso1.png",
        "viewbox_w": 557, "viewbox_h": 395,
        "locales": [
            {"unidad": "100-1", "label_at": [495, 305],
             "poligono": [[437.9, 90.6], [435, 362], [551, 368], [552, 240], [473, 239], [474, 128]]},
            {"unidad": "100-2", "label_at": [500, 86],
             "poligono": [[486.6, 54.4], [532.9, 60.6], [516.6, 80], [551.6, 111.9], [552.3, 152.5], [514.8, 151.3], [514.8, 116.3], [486.6, 116.9]]},
        ],
    },
    {
        "nombre": "Piso -2", "imagen": "pt_plano_piso2.png",
        "viewbox_w": 1485, "viewbox_h": 1059,
        "locales": [
            {"unidad": "100-9",
             "poligono": [[194, 137], [749, 137], [749, 199], [671, 199], [671, 468], [194, 468]]},
            {"unidad": "100-10", "rect": [191, 468, 682, 336]},
            {"unidad": "100-7", "rect": [671, 199, 114, 204]},
            {"unidad": "100-5", "rect": [783, 176, 452, 227]},
            {"unidad": "100-4", "rect": [1232, 178, 106, 225]},
            {"unidad": "100-8", "rect": [873, 439, 96, 168]},
            {"unidad": "100-6", "rect": [999, 439, 142, 168]},
            {"unidad": "100-3", "rect": [1191, 437, 186, 160]},
            {"unidad": "100-11",
             "poligono": [[190.1, 803.5], [1382, 801], [1379.2, 995], [1216, 995.3], [1050.1, 989.4],
                          [887.8, 976.5], [712.5, 954.1], [563.1, 927.1], [391.3, 878.8], [311.3, 854.1],
                          [240.7, 827.1], [218.4, 818.8]]},
        ],
    },
]


def _rect_a_poligono(x: float, y: float, w: float, h: float) -> list[list[float]]:
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

# Nombre corto para mostrar (tarjetas, tabs) — los labels largos son los que
# usa el rent roll internamente (_ACTIVO2_LABEL en rent_roll_stats.py) y se
# siguen usando tal cual para filtrar get_rubro_arrendatario/get_tipo_activo/
# get_perfil_vencimiento/get_unidades.
_DISPLAY = {"Torre A S.A.": "Torre A", "Inmob. Boulevard PT SpA": "Inmob. CdC"}


def _weighted_rent_uf_m2(units: list[dict]) -> float | None:
    """renta_uf de cada unidad es una tasa (UF/m2/mes) — el promedio de un
    grupo se pondera por m2, igual que en el resto del módulo (nunca se
    vuelve a dividir por superficie)."""
    m2_total = sum(u.get("m2") or 0.0 for u in units if u.get("renta_uf"))
    if not m2_total:
        return None
    peso = sum((u.get("renta_uf") or 0.0) * (u.get("m2") or 0.0) for u in units)
    return round(peso / m2_total, 4)


class PTViewProvider:
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)

    def build(self, period: str | None = None) -> dict:
        periods = self._common_periods()
        if not periods:
            return self._unavailable(period, periods)
        requested = period or periods[-1]
        observed = [item for item in periods if item <= requested]
        if not observed:
            return self._unavailable(requested, periods)
        selected = observed[-1]

        metrics = self._building_metrics(selected)
        buildings = []
        for asset_key, label in _ASSETS:
            metric = metrics.get(asset_key)
            if not metric:
                continue
            unidades = get_unidades("PT", selected, edificios=[label]) or []
            ocupadas = [u for u in unidades if not u["vacante"]]
            buildings.append({
                "asset_key": asset_key, "label": _DISPLAY.get(label, label), "period": selected,
                "occupancy_pct": 100.0 - metric["vacancy_pct"],
                "vacancy_pct": metric["vacancy_pct"], "vacant_m2": metric["vacant_m2"],
                "gla_m2": metric["gla_m2"],
                "rent_uf_m2": _weighted_rent_uf_m2(ocupadas),
                "rent_oficinas_uf_m2": _weighted_rent_uf_m2(
                    [u for u in ocupadas if u.get("tipo_activo") == "Oficinas"]
                ),
                "rent_locales_uf_m2": _weighted_rent_uf_m2(
                    [u for u in ocupadas if u.get("tipo_activo") == "Locales Comerciales"]
                ),
                "evidence_refs": [{
                    "id": f"pt:{asset_key}:{selected}",
                    "source": "v_vacancia_activo + raw_rent_roll_line", "period": selected,
                }],
            })
        status = "available" if requested == selected else "partial"
        return {
            "schema_version": "pt_view_v1",
            "context": {"group": "pt", "period": selected, "requested_period": requested},
            "buildings": buildings,
            "coverage": {"status": status, "observed_through": periods[-1], "reason_code": None if status == "available" else "period_not_observed"},
            "insights": self._consolidated_insights(selected),
            "plano_local_100": self._plano_local_100(selected),
        }

    def _plano_local_100(self, period: str) -> dict | None:
        """Plano real de Local 100 (Inmob. CdC) con estado de ocupación vivo
        por unidad — misma geometría que el fact sheet (ver
        _PLANO_LOCAL_100_PISOS arriba), datos de tools.db.rent_roll_stats
        .get_plano_locales. None si no hay rent roll para ese período (no se
        rellena con un plano vacío ni datos inventados)."""
        unidades = [loc["unidad"] for piso in _PLANO_LOCAL_100_PISOS for loc in piso["locales"]]
        estado = get_plano_locales("PT", period, _PLANO_LOCAL_100_EDIFICIO, unidades)
        if estado is None:
            return None
        pisos = []
        for piso in _PLANO_LOCAL_100_PISOS:
            locales = []
            for loc in piso["locales"]:
                info = estado.get(loc["unidad"], {})
                poligono = loc["poligono"] if "poligono" in loc else _rect_a_poligono(*loc["rect"])
                locales.append({
                    "unidad": loc["unidad"], "poligono": poligono,
                    "vacante": info.get("vacante", True),
                    "arrendatario": info.get("arrendatario"),
                    "m2": info.get("m2"), "renta_uf": info.get("renta_uf"),
                })
            pisos.append({
                "nombre": piso["nombre"], "imagen": piso["imagen"],
                "viewbox_w": piso["viewbox_w"], "viewbox_h": piso["viewbox_h"],
                "locales": locales,
            })
        return {"titulo": "Plano Local 100", "edificio": _DISPLAY.get("Inmob. Boulevard PT SpA"), "pisos": pisos}

    def _consolidated_insights(self, period: str) -> dict:
        all_edificios = [label for _, label in _ASSETS]
        scopes = [("consolidado", "Consolidado", all_edificios, [asset for asset, _ in _ASSETS])]
        scopes += [(asset_key, _DISPLAY.get(label, label), [label], [asset_key]) for asset_key, label in _ASSETS]
        return {
            scope_key: self._insights_for_scope(period, label, edificios, activo_keys)
            for scope_key, label, edificios, activo_keys in scopes
        }

    def _insights_for_scope(self, period: str, label: str, edificios: list[str], activo_keys: list[str]) -> dict:
        vencimiento = get_perfil_vencimiento("PT", period, edificios)
        anios = vencimiento["anios"] if vencimiento else []
        por_anio_uf = {
            anio: round(sum(vencimiento["por_anio"].get(ed, {}).get(anio, 0.0) for ed in edificios), 1)
            for anio in anios
        } if vencimiento else {}
        unidades_por_anio = {
            anio: _agrupar_categoria(
                [u for ed in edificios for u in vencimiento["unidades_por_anio"].get(ed, {}).get(anio, [])]
            )
            for anio in anios
        } if vencimiento else {}

        ocupadas = [u for u in (get_unidades("PT", period, edificios=edificios) or []) if not u["vacante"]]
        rubro = get_rubro_arrendatario("PT", period, edificios=edificios) or {}
        tipo_activo = get_tipo_activo("PT", period, edificios=edificios) or {}
        rubro_detalle, tipo_detalle = self._composicion_detalle(ocupadas, rubro, tipo_activo)
        arrendatarios = {t["arrendatario"]: t for t in _consolidar_por_arrendatario(ocupadas)}

        return {
            "label": label,
            "rubro_arrendatario": rubro, "rubro_arrendatario_detalle": rubro_detalle,
            "tipo_activo": tipo_activo, "tipo_activo_detalle": tipo_detalle,
            "vencimiento": {
                "anios": anios, "por_anio_uf": por_anio_uf,
                "plazo_medio_anios": vencimiento["plazo_medio_anios"] if vencimiento else None,
                "unidades_por_anio": unidades_por_anio,
            },
            "vacancia_historica": self._vacancia_historica(activo_keys),
            "arrendatarios": arrendatarios,
        }

    def _composicion_detalle(self, ocupadas: list[dict], rubro: dict, tipo_activo: dict) -> tuple[dict, dict]:
        categorias_rubro = set(rubro) - {"Otro"}
        rubro_detalle: dict[str, list] = {cat: [] for cat in rubro}
        for u in ocupadas:
            nombre = (u.get("tipo_arrendatario") or "").strip()
            if not nombre or nombre.lower() == "vacante":
                continue
            cat = nombre if nombre in categorias_rubro else "Otro"
            if cat in rubro_detalle:
                rubro_detalle[cat].append(u)

        tipo_detalle: dict[str, list] = {cat: [] for cat in tipo_activo}
        for u in ocupadas:
            cat = u.get("tipo_activo")
            if cat in tipo_detalle:
                tipo_detalle[cat].append(u)

        rubro_detalle = {cat: _agrupar_categoria(units) for cat, units in rubro_detalle.items()}
        tipo_detalle = {cat: _agrupar_categoria(units) for cat, units in tipo_detalle.items()}
        return rubro_detalle, tipo_detalle

    def _vacancia_historica(self, activo_keys: list[str]) -> list[dict]:
        placeholders = ",".join("?" for _ in activo_keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT periodo, SUM(m2_gla) AS gla, SUM(m2_vacantes) AS vac, COUNT(DISTINCT activo_key) AS n "
                f"FROM v_vacancia_activo WHERE activo_key IN ({placeholders}) GROUP BY periodo ORDER BY periodo",
                tuple(activo_keys),
            ).fetchall()
        needed = len(activo_keys)
        return [
            {
                "periodo": periodo, "gla_m2": round(gla, 1), "vacant_m2": round(vac, 1),
                "occupancy_pct": round(100.0 - (100.0 * vac / gla), 1),
            }
            for periodo, gla, vac, n in rows if n == needed and gla
        ]

    def _common_periods(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT periodo FROM v_vacancia_activo WHERE activo_key IN (?, ?) "
                "GROUP BY periodo HAVING COUNT(DISTINCT activo_key)=2 ORDER BY periodo",
                tuple(asset for asset, _ in _ASSETS),
            ).fetchall()
        return [row[0] for row in rows]

    def _building_metrics(self, period: str) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT activo_key, m2_gla, m2_vacantes, vacancia_pct FROM v_vacancia_activo "
                "WHERE periodo=? AND activo_key IN (?, ?)", (period, *(asset for asset, _ in _ASSETS)),
            ).fetchall()
        return {asset: {"gla_m2": float(gla), "vacant_m2": float(vacant), "vacancy_pct": 100.0 * float(vacancy)}
                for asset, gla, vacant, vacancy in rows}

    def _unavailable(self, requested: str | None, periods: list[str]) -> dict:
        return {"schema_version": "pt_view_v1", "context": {"group": "pt", "period": None, "requested_period": requested},
                "buildings": [], "coverage": {"status": "unavailable", "observed_through": periods[-1] if periods else None, "reason_code": "period_not_observed"}}

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
