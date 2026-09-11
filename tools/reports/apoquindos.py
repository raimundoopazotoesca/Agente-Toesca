"""Read-only, building-first report for Apoquindo 4501 and 4700."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.db.rent_roll_stats import (
    get_status_oficinas, get_status_locales,
    get_rubro_arrendatario, get_tipo_activo, get_perfil_vencimiento, get_unidades,
)


_ASSETS = (("Apo4501", "Apoquindo 4501"), ("Apo4700", "Apoquindo 4700"))


def _consolidar_por_arrendatario(units: list[dict]) -> list[dict]:
    """Agrupa unidades ocupadas por arrendatario para el drill-down de un
    gráfico (rubro/tipo de activo/vencimiento) — un arrendatario con más de
    un local u oficina aparecía como una fila por unidad; acá queda una sola
    fila con la superficie sumada y la renta (tasa UF/m2/mes) ponderada por
    m2, igual que el resto del módulo pondera montos.

    Estacionamientos: el m2 del rent roll ahí no es superficie real (mismo
    criterio que _celda en rent_roll_stats.py, que para ese tipo cuenta
    unidades en vez de sumar m2) — se sigue usando como ponderador interno de
    la renta (así se calcula el monto en todo el módulo), pero no se muestra
    como "m2"; se cuenta como unidades aparte, solo para mostrar."""
    grupos: dict[str, dict] = {}
    orden: list[str] = []
    for u in units:
        nombre = u.get("arrendatario") or "—"
        if nombre not in grupos:
            grupos[nombre] = {
                "arrendatario": nombre, "edificios": set(), "unidades": [],
                "m2_mostrado": 0.0, "m2_ponderador": 0.0, "peso": 0.0, "n_estacionamientos": 0,
            }
            orden.append(nombre)
        g = grupos[nombre]
        m2 = u.get("m2") or 0.0
        es_estacionamiento = u.get("tipo_activo") == "Estacionamientos"
        g["edificios"].add(u.get("edificio"))
        g["unidades"].append({
            "edificio": u.get("edificio"), "unidad": u.get("unidad"), "tipo_activo": u.get("tipo_activo"),
            "m2": u.get("m2"), "renta_uf": u.get("renta_uf"), "vencimiento": u.get("vencimiento"),
            "fecha_inicio": u.get("fecha_inicio"),
        })
        g["m2_ponderador"] += m2
        g["peso"] += (u.get("renta_uf") or 0.0) * m2
        if es_estacionamiento:
            g["n_estacionamientos"] += 1
        else:
            g["m2_mostrado"] += m2
    out = []
    for nombre in orden:
        g = grupos[nombre]
        out.append({
            "arrendatario": g["arrendatario"],
            "vacante": False,
            "edificios": sorted(e for e in g["edificios"] if e),
            "unidades": g["unidades"],
            "n_unidades": len(g["unidades"]),
            "m2": round(g["m2_mostrado"], 1),
            "n_estacionamientos": g["n_estacionamientos"],
            "renta_uf": round(g["peso"] / g["m2_ponderador"], 2) if g["m2_ponderador"] else None,
            # Monto total (peso ya es renta_uf×m2 sumado) — no "renta_uf×m2"
            # mostrado, que da 0 para estacionamientos (su m2 mostrado es 0).
            "monto_uf": round(g["peso"], 1),
        })
    out.sort(key=lambda t: t["monto_uf"], reverse=True)
    return out


def _by_building(units: list[dict]) -> list[dict]:
    """Monto mensual (UF) por edificio a partir de las unidades crudas (antes
    de consolidar por arrendatario, que ya no conserva el m2 por unidad
    individual necesario para este desglose)."""
    montos: dict[str, float] = {}
    for u in units:
        edificio = u.get("edificio")
        if not edificio:
            continue
        montos[edificio] = montos.get(edificio, 0.0) + (u.get("renta_uf") or 0.0) * (u.get("m2") or 0.0)
    return sorted(
        ({"edificio": ed, "uf": round(uf, 1)} for ed, uf in montos.items()),
        key=lambda row: row["uf"], reverse=True,
    )


def _agrupar_categoria(units: list[dict]) -> dict:
    """Payload de drill-down para una barra: desglose por edificio (calculado
    sobre las unidades crudas) + lista de arrendatarios consolidados (para no
    repetir filas cuando uno tiene más de un local/oficina)."""
    return {"by_building": _by_building(units), "tenants": _consolidar_por_arrendatario(units)}


class ApoquindosViewProvider:
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)

    def build(self, period: str | None = None) -> dict:
        periods = self._common_periods()
        requested = period or periods[-1]
        observed = [item for item in periods if item <= requested]
        if not observed:
            return self._unavailable(requested, periods)
        selected = observed[-1]
        floors = get_status_oficinas("Apoquindo", selected, [label for _, label in _ASSETS]) or {}
        locals_by_building = get_status_locales("Apoquindo", selected, [label for _, label in _ASSETS]) or {}
        rows = self._building_metrics(selected)
        buildings = []
        for asset_key, label in _ASSETS:
            metric = rows[asset_key]
            layout = floors.get(label, {})
            local_data = locals_by_building.get(label, {})
            buildings.append({
                "asset_key": asset_key, "label": label, "period": selected,
                "occupancy_pct": 100.0 - metric["vacancy_pct"],
                "vacancy_pct": metric["vacancy_pct"], "vacant_m2": metric["vacant_m2"],
                "gla_m2": metric["gla_m2"], "floors": [
                    {"floor": floor["piso"], "occupancy_pct": floor["ocupado_pct"],
                     "vacant_m2": round(floor["m2"] * (100 - floor["ocupado_pct"]) / 100, 1),
                     "units": floor["unidades"]}
                    for floor in layout.get("pisos", [])
                ],
                "local_status": {"status": "available" if local_data.get("locales") else "unavailable",
                                 "occupancy_pct": local_data.get("ocupacion_pct"),
                                 "reason_code": None if local_data.get("locales") else "local_layout_not_observed"},
                "locals": local_data.get("locales", []),
                "evidence_refs": [{"id": f"apoquindos:{asset_key}:{selected}", "source": "v_vacancia_activo + raw_rent_roll_line", "period": selected}],
            })
        status = "available" if requested == selected else "partial"
        return {
            "schema_version": "apoquindos_view_v1",
            "context": {"group": "apoquindos", "period": selected, "requested_period": requested},
            "buildings": buildings,
            "coverage": {"status": status, "observed_through": periods[-1], "reason_code": None if status == "available" else "period_not_observed"},
            "insights": self._consolidated_insights(selected),
        }

    def _consolidated_insights(self, period: str) -> dict:
        """Gráficos por scope — consolidado (Apo4501 + Apo4700) y cada
        edificio por separado, para el selector de la vista — reutilizando
        las mismas funciones de rent_roll_stats que alimentan el fact sheet:
        ninguna regla de negocio nueva, solo se ensambla la respuesta."""
        all_edificios = [label for _, label in _ASSETS]
        scopes = [("consolidado", "Consolidado", all_edificios, [asset for asset, _ in _ASSETS])]
        scopes += [(asset_key, label, [label], [asset_key]) for asset_key, label in _ASSETS]
        return {
            scope_key: self._insights_for_scope(period, label, edificios, activo_keys)
            for scope_key, label, edificios, activo_keys in scopes
        }

    def _insights_for_scope(self, period: str, label: str, edificios: list[str], activo_keys: list[str]) -> dict:
        vencimiento = get_perfil_vencimiento("Apoquindo", period, edificios)
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

        ocupadas = [u for u in (get_unidades("Apoquindo", period, edificios=edificios) or []) if not u["vacante"]]
        rubro = get_rubro_arrendatario("Apoquindo", period, edificios=edificios) or {}
        tipo_activo = get_tipo_activo("Apoquindo", period, edificios=edificios) or {}
        rubro_detalle, tipo_detalle = self._composicion_detalle(ocupadas, rubro, tipo_activo)
        # Perfil completo de cada arrendatario (todas sus unidades, sin
        # importar rubro/tipo/año) — para el drill-down de "ver arrendatario"
        # desde cualquier tarjeta (gráfico o piso/local).
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
        """Unidades ocupadas detrás de cada barra de rubro/tipo de activo,
        para el drill-down al hacer click — agrupa las mismas filas crudas
        (get_unidades) replicando exactamente los buckets que ya calcularon
        get_rubro_arrendatario/get_tipo_activo (top-N + "Otro" incluido), sin
        volver a clasificar nada."""
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

    def _unavailable(self, requested: str, periods: list[str]) -> dict:
        return {"schema_version": "apoquindos_view_v1", "context": {"group": "apoquindos", "period": None, "requested_period": requested},
                "buildings": [], "coverage": {"status": "unavailable", "observed_through": periods[-1] if periods else None, "reason_code": "period_not_observed"}}

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
