"""Read-only, normalized database schema discovery.

``source_category`` is deliberately structural and deterministic: views are
``view``; table names prefixed ``raw_``, ``dim_`` and ``derived_`` map to
``raw``, ``dimension`` and ``derived`` respectively; every other table is
``other``. Relationships are emitted only from explicit database foreign keys.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedSchemaResult:
    dialect: str
    metadata_version: str
    objects: tuple[SchemaObject, ...]

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
        matched = [obj for score, obj in ranked if score > 0]
        matched.sort(key=lambda obj: (-self._score(obj, query_tokens), obj.name))
        return NormalizedSchemaResult(self.dialect, self.metadata_version, tuple(matched[:effective_limit]))

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
        return SchemaObject(
            name=name,
            kind=kind,
            source_category=_source_category(name, kind),
            columns=columns,
            relationships=relationships,
        )

    @staticmethod
    def _score(obj: SchemaObject, query_tokens: tuple[str, ...]) -> int:
        name_tokens = set(_tokens(obj.name))
        column_tokens = {token for column in obj.columns for token in _tokens(column.name)}
        description_tokens = set(_tokens(obj.description or ""))
        score = 0
        for token in query_tokens:
            if token in name_tokens:
                score += 10
            if token in column_tokens:
                score += 3
            if token in description_tokens:
                score += 1
        return score


def _effective_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_SCHEMA_SEARCH_LIMIT
    return min(limit, MAX_SCHEMA_SEARCH_LIMIT)


def _tokens(value: str) -> tuple[str, ...]:
    normalized = re.sub(r"[_\-\s]+", " ", value.casefold())
    return tuple(token for token in re.split(r"[^\w]+", normalized) if token)


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
