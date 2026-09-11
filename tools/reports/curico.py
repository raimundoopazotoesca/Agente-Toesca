"""Read-only report for Mall Curicó (mall TresA, un solo edificio)."""
from __future__ import annotations

from pathlib import Path

from tools.reports.single_asset_insights import SingleAssetViewProvider


class CuricoViewProvider(SingleAssetViewProvider):
    schema_version = "curico_view_v1"
    group = "curico"

    def __init__(self, db_path: Path):
        # activo_key en dim_activo/v_vacancia_activo es "Mall Curicó", pero el
        # rent roll usa "Curicó" como activo2 crudo (ver raw_rent_roll_line).
        super().__init__(db_path, activo_key="Mall Curicó", edificio_label="Curicó", display_label="Mall Curicó")
