from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tools.datasets.models import DatasetCatalog, DatasetDefinition


CATALOG_PATH = Path(__file__).with_name("catalog_v1.yaml")
_REQUIRED = {
    "dataset_key", "semantic_version", "object_name", "grain", "grain_description", "row_represents",
    "description", "dimensions", "fields", "field_descriptions", "field_value_domains", "semantic_fields", "provenance_fields", "status",
}


class DatasetCatalogValidationError(ValueError):
    pass


def _dataset(raw: Any) -> DatasetDefinition:
    if not isinstance(raw, dict) or set(raw) != _REQUIRED:
        raise DatasetCatalogValidationError("malformed dataset definition")
    sequence_fields = ("dimensions", "fields", "semantic_fields", "provenance_fields")
    if any(not isinstance(raw[name], list) or not all(isinstance(value, str) for value in raw[name]) for name in sequence_fields):
        raise DatasetCatalogValidationError("malformed dataset definition fields")
    field_descriptions = raw["field_descriptions"]
    if (not isinstance(field_descriptions, dict)
            or set(field_descriptions) != set(raw["fields"])
            or not all(isinstance(name, str) and isinstance(description, str) and description
                       for name, description in field_descriptions.items())):
        raise DatasetCatalogValidationError("malformed dataset field descriptions")
    domains = raw["field_value_domains"]
    if not isinstance(domains, dict) or not set(domains) <= set(raw["fields"]):
        raise DatasetCatalogValidationError("malformed dataset field value domains")
    normalized_domains: dict[str, dict[str, object]] = {}
    for field, domain in domains.items():
        if not isinstance(domain, dict) or set(domain) != {"type", "values"}:
            raise DatasetCatalogValidationError("malformed dataset field value domain")
        kind, values = domain["type"], domain["values"]
        if kind == "enum":
            if (not isinstance(values, list) or not values
                    or not all(isinstance(value, str) and value for value in values)
                    or len(values) != len(set(values))):
                raise DatasetCatalogValidationError("invalid enum value domain")
        elif kind == "boolean":
            if values != [0, 1] or not all(type(value) is int for value in values):
                raise DatasetCatalogValidationError("invalid boolean value domain")
        else:
            raise DatasetCatalogValidationError("unsupported value domain type")
        normalized_domains[field] = {"type": kind, "values": tuple(values)}
    if raw["status"] != "active" or raw["grain"] != "rent_roll_row":
        raise DatasetCatalogValidationError("unsupported dataset status or grain")
    return DatasetDefinition(
        dataset_key=str(raw["dataset_key"]), semantic_version=str(raw["semantic_version"]),
        object_name=str(raw["object_name"]), grain=raw["grain"],
        grain_description=str(raw["grain_description"]), row_represents=str(raw["row_represents"]),
        description=str(raw["description"]),
        dimensions=tuple(raw["dimensions"]), fields=tuple(raw["fields"]),
        field_descriptions=dict(field_descriptions), field_value_domains=normalized_domains,
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
