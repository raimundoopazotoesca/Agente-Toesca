"""Read-only composition for the Vacancy Report v1 contract."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from tools.analytics.catalog import load_metric_catalog
from tools.analytics.models import FallbackAccess


_FUNDS = ("PT", "Apo", "TRI")
_WINDOW_MONTHS = {"6M": 6, "12M": 12, "24M": 24, "historico": None}


@dataclass(frozen=True)
class VacancyReportContext:
    fund: str
    period: str | None = None
    window: str = "12M"
    parking_scope: str = "exclude"
    asset: str | None = None


class VacancyReportProvider:
    """Normalizes existing governed vacancy outputs into one report document.

    This class deliberately does not implement vacancy formulae or source
    fallback rules. Those remain in the analytics catalog and canonical views.
    """

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._catalog = load_metric_catalog()

    def build(self, context: VacancyReportContext) -> dict:
        self._validate_context(context)
        scope_fund = self._asset_fund(context.asset) if context.asset else context.fund
        periods = self._asset_periods(context.asset) if context.asset else self._available_periods(scope_fund)
        requested = context.period or periods[-1]
        selected = self._resolve_period(scope_fund, requested, periods)
        if selected is None:
            return self._unavailable_report(context, requested, periods)

        rows = self._asset_history(context.asset, scope_fund, context.parking_scope) if context.asset else self._history(scope_fund, context.parking_scope)
        visible_rows = self._apply_window(rows, context.window)
        current = next(row for row in rows if row["period"] == selected)
        requested_available = requested == selected
        overall_status = "available" if requested_available else "partial"
        reason_code = None if requested_available else "period_not_observed"
        evidence_refs = current["evidence_refs"]
        return {
            "schema_version": "vacancy_report_v1",
            "context": {
                "report_type": "vacancy", "fund": scope_fund, "period": selected,
                "requested_period": requested, "asset": context.asset, "building": None,
                "space_type": None, "window": context.window, "parking_scope": context.parking_scope,
                "available_filters": self._available_filters(scope_fund, periods),
            },
            "summary": {
                "status": overall_status,
                "metrics": [
                    self._metric(self._vacancy_metric_id(context.parking_scope), current["vacancy_pct"], "pct_0_100", overall_status, evidence_refs),
                    self._metric("m2_vacantes", current["vacant_m2"], "m2", current["physical_status"], evidence_refs),
                    self._metric("gla_m2", current["gla_m2"], "m2", current["physical_status"], evidence_refs),
                ],
            },
            "history": {
                "status": overall_status, "metric_ids": [self._vacancy_metric_id(context.parking_scope), "m2_vacantes", "gla_m2"],
                "rows": visible_rows,
            },
            "breakdowns": [],
            "coverage": {
                "status": overall_status, "observed_through": periods[-1],
                "requested_period_available": requested_available, "reason_code": reason_code,
            },
            "freshness": {"data_through": periods[-1], "source_kind": "monthly_snapshot"},
            "provenance": {"evidence_refs": evidence_refs},
            "availability": {"status": overall_status, "reason_code": reason_code},
            "asset_overview": self._asset_overview(requested, context.parking_scope),
            "spatial_occupancy": self._spatial_occupancy(context.asset, selected),
            "extensions": {"movement_bridge": {
                "status": "unavailable", "reason_code": "movement_ledger_contract_pending",
            }},
        }

    def _history(self, fund: str, parking_scope: str) -> list[dict]:
        if fund == "TRI":
            return self._tri_history()
        return self._component_history(fund, parking_scope)

    def _available_periods(self, fund: str) -> list[str]:
        with self._connect() as conn:
            if fund == "TRI":
                rows = conn.execute(
                    "SELECT DISTINCT periodo FROM derived_kpi WHERE entidad_tipo='fondo' "
                    "AND entidad_key='TRI' AND kpi='vacancia_pct' ORDER BY periodo"
                ).fetchall()
            else:
                metric = self._catalog.metrics["vacancia_pct_fondo"]
                assert isinstance(metric.access, FallbackAccess)
                groups = metric.access.fallback.asset_groups[fund]
                assets = groups[0]
                placeholders = ",".join("?" for _ in assets)
                rows = conn.execute(
                    f"SELECT DISTINCT periodo FROM v_vacancia_activo WHERE activo_key IN ({placeholders}) ORDER BY periodo",
                    assets,
                ).fetchall()
        return [row[0] for row in rows]

    def _resolve_period(self, fund: str, requested: str, periods: list[str]) -> str | None:
        candidates = [item for item in periods if item <= requested]
        return candidates[-1] if candidates else None

    def _asset_fund(self, asset: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT fondo_key FROM dim_activo WHERE activo_key=?", (asset,)).fetchone()
        if row is None:
            raise ValueError("unsupported asset")
        return row[0]

    def _asset_periods(self, asset: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT periodo FROM v_vacancia_activo WHERE activo_key=? ORDER BY periodo", (asset,)
            ).fetchall()
        return [row[0] for row in rows]

    def _component_history(self, fund: str, parking_scope: str) -> list[dict]:
        metric = self._catalog.metrics["vacancia_pct_fondo"]
        assert isinstance(metric.access, FallbackAccess)
        assets = metric.access.fallback.asset_groups[fund][0]
        placeholders = ",".join("?" for _ in assets)
        source = "v_vacancia_activo" if parking_scope == "exclude" else "v_vacancia_activo_tipo"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT periodo, SUM(m2_vacantes), SUM(m2_gla) FROM {source} "
                f"WHERE activo_key IN ({placeholders}) GROUP BY periodo ORDER BY periodo",
                assets,
            ).fetchall()
        formula = f"rollup_ratio:{source}:[{','.join(assets)}]:sum(m2_vacantes)/sum(m2_gla)"
        return [self._physical_history_row(fund, period, vacant, gla, formula, parking_scope) for period, vacant, gla in rows if gla]

    def _asset_history(self, asset: str, fund: str, parking_scope: str) -> list[dict]:
        source = "v_vacancia_activo" if parking_scope == "exclude" else "v_vacancia_activo_tipo"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT periodo, SUM(m2_vacantes), SUM(m2_gla) FROM {source} "
                "WHERE activo_key=? GROUP BY periodo ORDER BY periodo", (asset,)
            ).fetchall()
        formula = f"rollup_ratio:{source}:[{asset}]:sum(m2_vacantes)/sum(m2_gla)"
        return [{
            "period": period, "vacancy_pct": 100.0 * float(vacant) / float(gla),
            "vacant_m2": float(vacant), "gla_m2": float(gla), "status": "available",
            "physical_status": "available",
            "evidence_refs": [self._evidence_ref(fund, period, {"formula": formula, "source_group": [asset]}, parking_scope)],
        } for period, vacant, gla in rows if vacant is not None and gla]

    def _tri_history(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT periodo, valor, formula, ingest_run_id FROM derived_kpi WHERE entidad_tipo='fondo' "
                "AND entidad_key='TRI' AND kpi='vacancia_pct' ORDER BY periodo"
            ).fetchall()
        return [{
            "period": period, "vacancy_pct": value, "vacant_m2": None, "gla_m2": None,
            "status": "unavailable", "physical_status": "unavailable",
            "evidence_refs": [self._evidence_ref("TRI", period, {"formula": formula, "ingest_run_id": ingest_run_id})],
        } for period, value, formula, ingest_run_id in rows]

    def _physical_history_row(self, fund: str, period: str, vacant: float, gla: float, formula: str,
                              parking_scope: str) -> dict:
        provenance = {"formula": formula, "source_group": self._source_group(fund)}
        return {
            "period": period, "vacancy_pct": 100.0 * float(vacant) / float(gla),
            "vacant_m2": float(vacant), "gla_m2": float(gla), "status": "available",
            "physical_status": "available", "evidence_refs": [self._evidence_ref(fund, period, provenance, parking_scope)],
        }

    def _source_group(self, fund: str) -> list[str]:
        metric = self._catalog.metrics["vacancia_pct_fondo"]
        assert isinstance(metric.access, FallbackAccess)
        return list(metric.access.fallback.asset_groups[fund][0])

    @staticmethod
    def _metric(metric_id: str, value: float | None, unit: str, status: str, evidence_refs: list[dict]) -> dict:
        return {"metric_id": metric_id, "value": value, "unit": unit, "status": status,
                "comparison": {"mom_pp": None, "yoy_pp": None}, "evidence_refs": evidence_refs}

    @staticmethod
    def _vacancy_metric_id(parking_scope: str) -> str:
        return "vacancia_pct_fondo" if parking_scope == "exclude" else "vacancia_fisica_pct_incluye_estacionamientos"

    @classmethod
    def _evidence_ref(cls, fund: str, period: str, provenance: dict, parking_scope: str = "exclude") -> dict:
        return {"id": f"vacancy:{fund}:{period}:{parking_scope}", "metric_id": cls._vacancy_metric_id(parking_scope),
                "period": period, "scope": {"fund": fund}, "source": provenance.get("formula"),
                "provenance": provenance}

    def _asset_overview(self, requested: str, parking_scope: str) -> dict:
        source = "v_vacancia_activo" if parking_scope == "exclude" else "v_vacancia_activo_tipo"
        parking_filter = "" if parking_scope == "include" else "AND COALESCE(a.tipo, '') != 'parking'"
        with self._connect() as conn:
            rows = conn.execute(
                f"""WITH observed AS (
                       SELECT activo_key, MAX(periodo) AS period
                       FROM {source} WHERE periodo <= ? GROUP BY activo_key
                    )
                    SELECT a.activo_key, a.nombre, a.fondo_key, a.categoria, v.periodo,
                           SUM(v.m2_vacantes), SUM(v.m2_gla)
                    FROM dim_activo a JOIN observed o ON o.activo_key=a.activo_key
                    JOIN {source} v ON v.activo_key=o.activo_key AND v.periodo=o.period
                    WHERE a.activo_key != 'Strip Machalí' {parking_filter}
                    GROUP BY a.activo_key, a.nombre, a.fondo_key, a.categoria, v.periodo
                    HAVING SUM(v.m2_gla) > 0
                    ORDER BY (SUM(v.m2_vacantes) * 1.0 / SUM(v.m2_gla)) DESC, a.nombre""",
                (requested,),
            ).fetchall()
        result = []
        for asset, label, fund, category, period, vacant, gla in rows:
            spatial = self._spatial_occupancy(asset, period)
            physical_available = vacant is not None and gla is not None and float(gla) > 0
            result.append({
                "asset_key": asset, "label": label, "fund": fund, "category": category,
                "period": period, "vacancy_pct": 100.0 * float(vacant) / float(gla) if physical_available else None,
                "vacant_m2": float(vacant) if vacant is not None else None,
                "gla_m2": float(gla) if gla is not None else None,
                "status": "available" if physical_available else "partial",
                "spatial_status": spatial["status"],
                "evidence_refs": [self._evidence_ref(fund, period, {"source": source}, parking_scope)],
            })
        return {"status": "available" if result else "unavailable", "rows": result}

    def _spatial_occupancy(self, asset: str | None, period: str) -> dict:
        if not asset:
            return {"status": "unavailable", "reason_code": "asset_not_selected", "buildings": []}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT entidad_key, kpi, valor, formula, ingest_run_id FROM derived_kpi "
                "WHERE entidad_tipo='activo' AND periodo=? AND entidad_key LIKE ? "
                "AND kpi IN ('vacancia_pct_piso', 'vacancia_m2_piso') ORDER BY entidad_key, kpi",
                (period, f"{asset}::%"),
            ).fetchall()
        floors: dict[tuple[str, str], dict] = {}
        for entity_key, kpi, value, formula, ingest_run_id in rows:
            parts = entity_key.split("::", 2)
            if len(parts) != 3:
                continue
            floor = floors.setdefault((parts[1], parts[2]), {
                "floor": parts[2], "vacancy_pct": None, "vacant_m2": None,
                "evidence_refs": [self._evidence_ref(parts[0], period, {"formula": formula, "ingest_run_id": ingest_run_id})],
            })
            floor["vacancy_pct" if kpi == "vacancia_pct_piso" else "vacant_m2"] = value
        if not floors:
            return {"status": "unavailable", "reason_code": "spatial_layout_not_observed", "buildings": []}
        buildings: dict[str, list[dict]] = {}
        for (building, _), floor in floors.items():
            buildings.setdefault(building, []).append(floor)
        return {"status": "available", "reason_code": None, "period": period, "buildings": [
            {"building": building, "floors": sorted(items, key=lambda item: item["floor"], reverse=True)}
            for building, items in buildings.items()
        ]}

    @staticmethod
    def _apply_window(rows: list[dict], window: str) -> list[dict]:
        months = _WINDOW_MONTHS[window]
        return rows if months is None else rows[-months:]

    @staticmethod
    def _available_filters(fund: str, periods: list[str]) -> dict:
        return {"fund": list(_FUNDS), "period": periods, "asset": [], "building": [], "space_type": []}

    @staticmethod
    def _validate_context(context: VacancyReportContext) -> None:
        if context.fund not in _FUNDS:
            raise ValueError("unsupported fund")
        if context.period is not None and len(context.period) != 7:
            raise ValueError("period must use YYYY-MM")
        if context.window not in _WINDOW_MONTHS:
            raise ValueError("unsupported report window")
        if context.parking_scope not in {"exclude", "include"}:
            raise ValueError("unsupported parking scope")

    def _unavailable_report(self, context: VacancyReportContext, requested: str, periods: list[str]) -> dict:
        reason = "no_observed_period" if not periods else "period_not_observed"
        return {
            "schema_version": "vacancy_report_v1",
            "context": {"report_type": "vacancy", "fund": context.fund, "period": None,
                        "requested_period": requested, "asset": context.asset, "building": None,
                        "space_type": None, "window": context.window, "parking_scope": context.parking_scope,
                        "available_filters": self._available_filters(context.fund, periods)},
            "summary": {"status": "unavailable", "metrics": []},
            "history": {"status": "unavailable", "metric_ids": [], "rows": []},
            "breakdowns": [],
            "coverage": {"status": "unavailable", "observed_through": periods[-1] if periods else None,
                         "requested_period_available": False, "reason_code": reason},
            "freshness": {"data_through": periods[-1] if periods else None, "source_kind": "monthly_snapshot"},
            "provenance": {"evidence_refs": []},
            "availability": {"status": "unavailable", "reason_code": reason},
            "asset_overview": {"status": "unavailable", "rows": []},
            "spatial_occupancy": self._spatial_occupancy(context.asset, requested),
            "extensions": {"movement_bridge": {"status": "unavailable", "reason_code": "movement_ledger_contract_pending"}},
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
