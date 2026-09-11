"""Read-only report for Sucden (bodega, un solo arrendatario con contrato
fijo). Sin gráficos de composición/vencimiento/vacancia histórica: con un
solo contrato esos gráficos serían una sola barra — no aportan nada que la
tarjeta de contrato no muestre ya. Ver tools/db/ingest_contratos_sucden_inmosa.py
para el origen del dato."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.db.rent_roll_stats import get_unidades

ACTIVO_KEY = "Sucden"
DISPLAY_LABEL = "Sucden"


class SucdenViewProvider:
    schema_version = "sucden_view_v1"

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

        unidades = get_unidades(ACTIVO_KEY, selected) or []
        ocupadas = [u for u in unidades if not u["vacante"]]
        contrato = ocupadas[0] if ocupadas else None

        status = "available" if requested == selected else "partial"
        return {
            "schema_version": self.schema_version,
            "context": {"group": "sucden", "period": selected, "requested_period": requested},
            "building": {
                "label": DISPLAY_LABEL, "period": selected,
                "occupancy_pct": 100.0 - metric["vacancy_pct"], "vacancy_pct": metric["vacancy_pct"],
                "vacant_m2": metric["vacant_m2"], "gla_m2": metric["gla_m2"],
            },
            "contrato": contrato,
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
            "context": {"group": "sucden", "period": None, "requested_period": requested},
            "building": None, "contrato": None,
            "coverage": {
                "status": "unavailable", "observed_through": periods[-1] if periods else None,
                "reason_code": "period_not_observed",
            },
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
