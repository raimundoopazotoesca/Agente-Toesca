"""Loads and validates the YAML semantic layer (semantic/) into memory."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import validate, ValidationError

SEMANTIC_DIR = Path(__file__).resolve().parents[2] / "semantic"


class SemanticValidationError(Exception):
    pass


@dataclass
class SemanticCatalog:
    metrics: dict[str, dict] = field(default_factory=dict)
    entities: dict[str, Any] = field(default_factory=dict)
    relationships: dict[str, Any] = field(default_factory=dict)
    synonyms: dict[str, Any] = field(default_factory=dict)
    domains: dict[str, Any] = field(default_factory=dict)


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_schema(schema_dir: Path, name: str) -> dict:
    with (schema_dir / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


_CACHE: dict[Path, SemanticCatalog] = {}


def load_semantic_catalog(semantic_dir: Path = SEMANTIC_DIR) -> SemanticCatalog:
    """Loads all semantic/*.yaml files, validates them, caches by directory."""
    if semantic_dir in _CACHE:
        return _CACHE[semantic_dir]

    schema_dir = semantic_dir / "schema"
    metric_schema = _load_schema(schema_dir, "metric.schema.json")
    entity_schema = _load_schema(schema_dir, "entity.schema.json")

    metrics: dict[str, dict] = {}
    metrics_dir = semantic_dir / "metrics"
    for metric_file in sorted(metrics_dir.glob("*.yaml")):
        data = _load_yaml(metric_file)
        try:
            validate(instance=data, schema=metric_schema)
        except ValidationError as exc:
            raise SemanticValidationError(f"{metric_file}: {exc.message}") from exc
        metrics[data["name"]] = data

    entities = _load_yaml(semantic_dir / "entities.yaml")
    try:
        validate(instance=entities, schema=entity_schema)
    except ValidationError as exc:
        raise SemanticValidationError(f"entities.yaml: {exc.message}") from exc

    catalog = SemanticCatalog(
        metrics=metrics,
        entities=entities,
        relationships=_load_yaml(semantic_dir / "relationships.yaml"),
        synonyms=_load_yaml(semantic_dir / "synonyms.yaml"),
        domains=_load_yaml(semantic_dir / "domains.yaml"),
    )
    _CACHE[semantic_dir] = catalog
    return catalog
