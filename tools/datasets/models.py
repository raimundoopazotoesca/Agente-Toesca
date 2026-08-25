from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_key: str
    semantic_version: str
    object_name: str
    grain: str
    grain_description: str
    row_represents: str
    description: str
    dimensions: tuple[str, ...]
    fields: tuple[str, ...]
    field_descriptions: dict[str, str]
    field_value_domains: dict[str, dict[str, object]]
    semantic_fields: tuple[str, ...]
    provenance_fields: tuple[str, ...]
    field_types: dict[str, str]
    measures: dict[str, dict[str, object]]
    status: str

    def schema_metadata(self) -> dict[str, object]:
        return {
            "dataset_key": self.dataset_key,
            "semantic_version": self.semantic_version,
            "grain": self.grain,
            "grain_description": self.grain_description,
            "row_represents": self.row_represents,
            "description": self.description,
            "dimensions": list(self.dimensions),
            "fields": self.field_descriptions,
            "field_value_domains": {
                field: {"type": domain["type"], "values": list(domain["values"])}
                for field, domain in self.field_value_domains.items()
            },
            "semantic_fields": list(self.semantic_fields),
            "provenance_fields": list(self.provenance_fields),
            "field_types": self.field_types,
            "measures": self.measures,
            "status": self.status,
        }


@dataclass(frozen=True)
class DatasetCatalog:
    version: int
    datasets: dict[str, DatasetDefinition]

    def as_dict(self) -> dict[str, object]:
        return {
            "catalog_version": self.version,
            "datasets": {key: asdict(value) for key, value in self.datasets.items()},
        }
