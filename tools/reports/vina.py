"""Read-only report for Viña Centro (mall TresA, un solo edificio)."""
from __future__ import annotations

from pathlib import Path

from tools.reports.single_asset_insights import SingleAssetViewProvider


class VinaViewProvider(SingleAssetViewProvider):
    schema_version = "vina_view_v1"
    group = "vina"

    def __init__(self, db_path: Path):
        # El activo2 crudo del rent roll ya coincide con el activo_key acá
        # (a diferencia de PT, que necesita _ACTIVO2_LABEL para traducir).
        super().__init__(db_path, activo_key="Viña Centro", edificio_label="Viña Centro", display_label="Viña Centro")
