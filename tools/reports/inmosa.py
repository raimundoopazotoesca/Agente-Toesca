"""Read-only report for INMOSA. Sin rent roll ingestado (0 filas en
raw_rent_roll_line a la fecha) — solo se muestran las métricas de ocupación
que sí existen en v_vacancia_activo. No hay composición por arrendatario,
tipo de activo ni vencimiento: mostrarlas requeriría inventar datos que no
existen en el sistema."""
from __future__ import annotations

from pathlib import Path
import sqlite3

ACTIVO_KEY = "INMOSA"
DISPLAY_LABEL = "INMOSA"


class InmosaViewProvider:
    schema_version = "inmosa_view_v1"

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)

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
            "context": {"group": "inmosa", "period": selected, "requested_period": requested},
            "building": {
                "label": DISPLAY_LABEL, "period": selected,
                "occupancy_pct": 100.0 - metric["vacancy_pct"], "vacancy_pct": metric["vacancy_pct"],
                "vacant_m2": metric["vacant_m2"], "gla_m2": metric["gla_m2"],
            },
            "detalle_disponible": False,
            "coverage": {
                "status": status, "observed_through": periods[-1],
                "reason_code": None if status == "available" else "period_not_observed",
            },
        }

    def _periods(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT periodo FROM v_vacancia_activo WHERE activo_key=? AND vacancia_pct IS NOT NULL ORDER BY periodo",
                (ACTIVO_KEY,),
            ).fetchall()
        return [row[0] for row in rows]

    def _metric(self, period: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT m2_gla, m2_vacantes, vacancia_pct FROM v_vacancia_activo WHERE activo_key=? AND periodo=?",
                (ACTIVO_KEY, period),
            ).fetchone()
        if not row:
            return None
        gla, vacante, vacancia_pct = row
        return {"gla_m2": float(gla), "vacant_m2": float(vacante or 0.0), "vacancy_pct": 100.0 * float(vacancia_pct or 0.0)}

    def _unavailable(self, requested: str | None, periods: list[str]) -> dict:
        return {
            "schema_version": self.schema_version,
            "context": {"group": "inmosa", "period": None, "requested_period": requested},
            "building": None, "detalle_disponible": False,
            "coverage": {
                "status": "unavailable", "observed_through": periods[-1] if periods else None,
                "reason_code": "period_not_observed",
            },
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
