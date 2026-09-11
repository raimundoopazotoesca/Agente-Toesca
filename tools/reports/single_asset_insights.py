"""Base compartida para reportes de un solo edificio respaldados por rent
roll (Viña Centro, Mall Curicó) — misma lógica de consolidación por
arrendatario que Apoquindos/PT (_consolidar_por_arrendatario,
_agrupar_categoria, importadas tal cual, sin duplicar reglas de negocio).
Sin selector de scope: acá solo hay un edificio, no dos para comparar."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.db import rent_roll_source
from tools.db.rent_roll_stats import (
    get_rubro_arrendatario, get_tipo_activo, get_perfil_vencimiento, get_unidades,
)
from tools.reports.apoquindos import _consolidar_por_arrendatario, _agrupar_categoria


class SingleAssetViewProvider:
    schema_version = "single_asset_view_v1"
    group = "single_asset"

    def __init__(self, db_path: Path, activo_key: str, edificio_label: str, display_label: str):
        self._db_path = Path(db_path)
        self.activo_key = activo_key
        self.edificio_label = edificio_label
        self.display_label = display_label

    def build(self, period: str | None = None) -> dict:
        periods = self._periods()
        if not periods:
            return self._unavailable(period, periods)
        requested = period or periods[-1]
        observed = [p for p in periods if p <= requested]
        if not observed:
            return self._unavailable(requested, periods)
        selected = observed[-1]
        metric = self._metric(selected)
        if metric is None:
            return self._unavailable(requested, periods)
        status = "available" if requested == selected else "partial"
        return {
            "schema_version": self.schema_version,
            "context": {"group": self.group, "period": selected, "requested_period": requested},
            "building": {
                "label": self.display_label, "period": selected,
                "occupancy_pct": 100.0 - metric["vacancy_pct"], "vacancy_pct": metric["vacancy_pct"],
                "vacant_m2": metric["vacant_m2"], "gla_m2": metric["gla_m2"],
            },
            "coverage": {
                "status": status, "observed_through": periods[-1],
                "reason_code": None if status == "available" else "period_not_observed",
            },
            "insights": self._insights(selected),
        }

    def _insights(self, period: str) -> dict:
        edificios = [self.edificio_label]
        vencimiento = get_perfil_vencimiento(self.activo_key, period, edificios)
        anios = vencimiento["anios"] if vencimiento else []
        por_anio_uf = {
            a: round(vencimiento["por_anio"].get(self.edificio_label, {}).get(a, 0.0), 1) for a in anios
        } if vencimiento else {}
        unidades_por_anio = {
            a: _agrupar_categoria(vencimiento["unidades_por_anio"].get(self.edificio_label, {}).get(a, []))
            for a in anios
        } if vencimiento else {}

        ocupadas = [u for u in (get_unidades(self.activo_key, period, edificios=edificios) or []) if not u["vacante"]]
        rubro = get_rubro_arrendatario(self.activo_key, period, edificios=edificios) or {}
        tipo_activo = get_tipo_activo(self.activo_key, period, edificios=edificios) or {}
        rubro_detalle, tipo_detalle = self._composicion_detalle(ocupadas, rubro, tipo_activo)
        arrendatarios = {t["arrendatario"]: t for t in _consolidar_por_arrendatario(ocupadas)}

        return {
            "label": self.display_label,
            "rubro_arrendatario": rubro, "rubro_arrendatario_detalle": rubro_detalle,
            "tipo_activo": tipo_activo, "tipo_activo_detalle": tipo_detalle,
            "vencimiento": {
                "anios": anios, "por_anio_uf": por_anio_uf,
                "plazo_medio_anios": vencimiento["plazo_medio_anios"] if vencimiento else None,
                "unidades_por_anio": unidades_por_anio,
            },
            "vacancia_historica": self._vacancia_historica(),
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

        return (
            {cat: _agrupar_categoria(units) for cat, units in rubro_detalle.items()},
            {cat: _agrupar_categoria(units) for cat, units in tipo_detalle.items()},
        )

    def _vacancia_historica(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT periodo, m2_gla, m2_vacantes FROM v_vacancia_activo "
                "WHERE activo_key=? AND vacancia_pct IS NOT NULL ORDER BY periodo",
                (self.activo_key,),
            ).fetchall()
        return [
            {
                "periodo": periodo, "gla_m2": round(gla, 1), "vacant_m2": round(vac, 1),
                "occupancy_pct": round(100.0 - (100.0 * vac / gla), 1),
            }
            for periodo, gla, vac in rows if gla
        ]

    def _periods(self) -> list[str]:
        """Intersección de períodos con vacancia observada (v_vacancia_activo)
        y con rent roll ingestado (raw_rent_roll_line) — para Viña/Curicó el
        rent roll suele ir un mes atrás de la vacancia (proveedores
        distintos), así que un período con vacancia pero sin rent roll
        dejaría los gráficos de composición vacíos sin ser realmente el
        último dato disponible."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT periodo FROM v_vacancia_activo WHERE activo_key=? AND vacancia_pct IS NOT NULL ORDER BY periodo",
                (self.activo_key,),
            ).fetchall()
        vacancia_periods = {row[0] for row in rows}
        rent_roll_periods = set(rent_roll_source.periodos_disponibles(self.activo_key))
        return sorted(vacancia_periods & rent_roll_periods)

    def _metric(self, period: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT m2_gla, m2_vacantes, vacancia_pct FROM v_vacancia_activo WHERE activo_key=? AND periodo=?",
                (self.activo_key, period),
            ).fetchone()
        if not row:
            return None
        gla, vacante, vacancia_pct = row
        return {"gla_m2": float(gla), "vacant_m2": float(vacante or 0.0), "vacancy_pct": 100.0 * float(vacancia_pct or 0.0)}

    def _unavailable(self, requested: str | None, periods: list[str]) -> dict:
        return {
            "schema_version": self.schema_version,
            "context": {"group": self.group, "period": None, "requested_period": requested},
            "building": None,
            "coverage": {
                "status": "unavailable", "observed_through": periods[-1] if periods else None,
                "reason_code": "period_not_observed",
            },
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
