"""Canonical entity metadata, deliberately independent of metric observations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import re
import unicodedata

import yaml

from tools.analytics.models import EntityDefinition, EntityType


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"\w+", text))


@dataclass(frozen=True)
class EntityDefinitions:
    entities: tuple[EntityDefinition, ...]

    def resolve_exact(self, query: str, entity_type: str) -> EntityDefinition | None:
        normalized = _normalize(query)
        matches = [
            entity for entity in self.entities
            if entity.entity_type.value == entity_type
            and normalized in {_normalize(alias) for alias in entity.aliases}
        ]
        return matches[0] if len(matches) == 1 else None

    def resolve_fuzzy(self, query: str, entity_type: str) -> EntityDefinition | None:
        """Return one cautious typed typo candidate, never an autocorrection."""
        normalized = _normalize(query)
        matches = [
            entity for entity in self.entities
            if entity.entity_type.value == entity_type
            and any(_safe_typo_match(normalized, _normalize(alias)) for alias in entity.aliases)
        ]
        return matches[0] if len(matches) == 1 else None


def _safe_typo_match(query: str, alias: str) -> bool:
    if query == alias or not query or not alias:
        return False
    if len(query) == len(alias) == 2:
        return query == alias[::-1]
    if len(query) < 4 or len(alias) < 4:
        return False
    return _damerau_levenshtein(query, alias) <= 1


def _damerau_levenshtein(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            insertion = current[right_index - 1] + 1
            deletion = previous[right_index] + 1
            substitution = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insertion, deletion, substitution))
            if left_index > 1 and right_index > 1 and left_char == right[right_index - 2] and left[left_index - 2] == right_char:
                current[right_index] = min(current[right_index], previous[right_index - 2] + 1)
        previous = current
    return previous[-1]


def load_entity_definitions(path: Path) -> EntityDefinitions:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entities: list[EntityDefinition] = []
    for section, entity_type in (("fondos", EntityType.FUND), ("activos", EntityType.ASSET)):
        for entity_id, values in (raw.get(section) or {}).items():
            if not isinstance(values, dict) or not isinstance(values.get("nombre"), str):
                raise ValueError(f"malformed {section} entity definition")
            aliases = values.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias for alias in aliases):
                raise ValueError(f"malformed aliases for {entity_id}")
            entities.append(EntityDefinition(str(entity_id), entity_type, values["nombre"], tuple(aliases)))
    return EntityDefinitions(tuple(entities))
