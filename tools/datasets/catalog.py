from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tools.datasets.models import DatasetCatalog, DatasetDefinition


CATALOG_PATH = Path(__file__).with_name("catalog_v1.yaml")
_REQUIRED = {
    "dataset_key", "semantic_version", "object_name", "grain", "description", "dimensions",
    "fields", "semantic_fields", "provenance_fields", "status",
}


class DatasetCatalogValidationError(ValueError):
    pass


def _dataset(raw: Any) -> DatasetDefinition:
    if not isinstance(raw, dict) or set(raw) != _REQUIRED:
        raise DatasetCatalogValidationError("malformed dataset definition")
    sequence_fields = ("dimensions", "fields", "semantic_fields", "provenance_fields")
    if any(not isinstance(raw[name], list) or not all(isinstance(value, str) for value in raw[name]) for name in sequence_fields):
        raise DatasetCatalogValidationError("malformed dataset definition fields")
    if raw["status"] != "active" or raw["grain"] != "rent_roll_row":
        raise DatasetCatalogValidationError("unsupported dataset status or grain")
    return DatasetDefinition(
        dataset_key=str(raw["dataset_key"]), semantic_version=str(raw["semantic_version"]),
        object_name=str(raw["object_name"]), grain=raw["grain"], description=str(raw["description"]),
        dimensions=tuple(raw["dimensions"]), fields=tuple(raw["fields"]),
        semantic_fields=tuple(raw["semantic_fields"]), provenance_fields=tuple(raw["provenance_fields"]),
        status=raw["status"],
    )


def load_dataset_catalog(path: Path | None = None) -> DatasetCatalog:
    raw = yaml.safe_load((path or CATALOG_PATH).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("catalog_version") != 1 or not isinstance(raw.get("datasets"), list):
        raise DatasetCatalogValidationError("malformed dataset catalog")
    definitions = [_dataset(value) for value in raw["datasets"]]
    keys = [definition.dataset_key for definition in definitions]
    objects = [definition.object_name for definition in definitions]
    if not keys or len(keys) != len(set(keys)) or len(objects) != len(set(objects)):
        raise DatasetCatalogValidationError("duplicate or empty dataset identity")
    return DatasetCatalog(1, {definition.dataset_key: definition for definition in definitions})
