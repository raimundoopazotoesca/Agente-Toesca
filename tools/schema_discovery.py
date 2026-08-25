"""Read-only, normalized database schema discovery.

``source_category`` is deliberately structural and deterministic: views are
``view``; table names prefixed ``raw_``, ``dim_`` and ``derived_`` map to
``raw``, ``dimension`` and ``derived`` respectively; every other table is
``other``. Relationships are emitted only from explicit database foreign keys.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from tools.datasets.catalog import load_dataset_catalog


DEFAULT_SCHEMA_SEARCH_LIMIT = 5
MAX_SCHEMA_SEARCH_LIMIT = 10
METADATA_VERSION = "sqlite_schema_v1"


@dataclass(frozen=True)
class SchemaColumn:
    name: str
    type: str
    nullable: bool


@dataclass(frozen=True)
class SchemaRelationship:
    column: str
    target_object: str
    target_column: str


@dataclass(frozen=True)
class SchemaObject:
    name: str
    kind: str
    source_category: str
    columns: tuple[SchemaColumn, ...]
    relationships: tuple[SchemaRelationship, ...]
    description: str | None = None
    dataset: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedSchemaResult:
    dialect: str
    metadata_version: str
    objects: tuple[SchemaObject, ...]
    candidate_scores: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.candidate_scores is None:
            object.__setattr__(self, "candidate_scores", {})

    def as_dict(self) -> dict[str, object]:
        return {
            "dialect": self.dialect,
            "metadata_version": self.metadata_version,
            "objects": [obj.as_dict() for obj in self.objects],
        }


class SchemaIntrospector(Protocol):
    def search(self, query: str, limit: int | None = None) -> NormalizedSchemaResult: ...


class SQLiteSchemaIntrospector:
    """Search SQLite metadata without exposing rows, DDL, or inferred links."""

    dialect = "sqlite"
    metadata_version = METADATA_VERSION

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        catalog = load_dataset_catalog()
        self._datasets_by_object = {dataset.object_name: dataset for dataset in catalog.datasets.values()}

    def search(self, query: str, limit: int | None = None) -> NormalizedSchemaResult:
        query_tokens = _tokens(query)
        if not query_tokens:
            return NormalizedSchemaResult(self.dialect, self.metadata_version, ())
        effective_limit = _effective_limit(limit)
        conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            objects = [self._object(conn, name, kind) for name, kind in conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )]
        finally:
            conn.close()
        ranked = [(self._score(obj, query_tokens), obj) for obj in objects]
        matched = [(score, obj) for score, obj in ranked if score > 0]
        matched.sort(key=lambda item: (-item[0], item[1].name))
        selected = matched[:effective_limit]
        return NormalizedSchemaResult(
            self.dialect, self.metadata_version, tuple(obj for _, obj in selected),
            {obj.name: score for score, obj in selected},
        )

    def _object(self, conn: sqlite3.Connection, name: str, kind: str) -> SchemaObject:
        identifier = _quote_identifier(name)
        columns = tuple(
            SchemaColumn(name=row[1], type=row[2] or "", nullable=not bool(row[3]) and not bool(row[5]))
            for row in conn.execute(f"PRAGMA table_info({identifier})")
        )
        relationships = tuple(
            SchemaRelationship(column=row[3], target_object=row[2], target_column=row[4])
            for row in conn.execute(f"PRAGMA foreign_key_list({identifier})")
            if row[4] is not None
        )
        dataset = self._datasets_by_object.get(name)
        return SchemaObject(
            name=name,
            kind=kind,
            source_category=_source_category(name, kind),
            columns=columns,
            relationships=relationships,
            description=dataset.description if dataset else None,
            dataset=dataset.schema_metadata() if dataset else None,
        )

    @staticmethod
    def _score(obj: SchemaObject, query_tokens: tuple[str, ...]) -> int:
        dataset = obj.dataset or {}
        field_descriptions = dataset.get("fields", {})
        sources = (
            (10, _tokens(obj.name)),
            (3, tuple(token for column in obj.columns for token in _tokens(column.name))),
            (4, _tokens(obj.description or "")),
            (5, _tokens(str(dataset.get("row_represents", "")))),
            (4, _tokens(str(dataset.get("grain_description", "")))),
            (3, _tokens(str(dataset.get("grain", "")))),
            (3, tuple(token for dimension in dataset.get("dimensions", []) for token in _tokens(str(dimension)))),
            (3, tuple(token for field in dataset.get("fields", {}) for token in _tokens(str(field)))),
            (4, tuple(token for description in field_descriptions.values() for token in _tokens(str(description))) if isinstance(field_descriptions, dict) else ()),
            (2, tuple(token for field in dataset.get("semantic_fields", []) for token in _tokens(str(field)))),
            (2, tuple(token for field in dataset.get("provenance_fields", []) for token in _tokens(str(field)))),
        )
        # A dimension or field can be represented in physical columns and in
        # the catalog. Count its strongest structural evidence once per token,
        # rather than inflating generic terms through duplicated metadata.
        score = sum(
            max((weight for weight, values in sources if token in values), default=0)
            for token in query_tokens
        )
        return score + (1 if score > 0 and dataset.get("status") == "active" else 0)


def _effective_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_SCHEMA_SEARCH_LIMIT
    return min(limit, MAX_SCHEMA_SEARCH_LIMIT)


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[_\-\s]+", " ", normalized)
    return tuple(
        _singular(token)
        for token in re.split(r"[^\w]+", normalized)
        if len(token) > 1
    )


def _singular(token: str) -> str:
    """Conservative generic plural normalization for lexical metadata search."""
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _source_category(name: str, kind: str) -> str:
    if kind == "view":
        return "view"
    if name.startswith("raw_"):
        return "raw"
    if name.startswith("dim_"):
        return "dimension"
    if name.startswith("derived_"):
        return "derived"
    return "other"
