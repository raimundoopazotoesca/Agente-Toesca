"""Resolves free-text mentions of funds/assets to their canonical keys
using semantic/synonyms.yaml and semantic/entities.yaml."""
from __future__ import annotations

import unicodedata

from tools.analyst.semantic_loader import SemanticCatalog, load_semantic_catalog

_KIND_TO_SECTION = {"fondo": "fondos", "activo": "activos"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()


def resolve_entity(text: str, kind: str, catalog: SemanticCatalog | None = None) -> str | None:
    if kind not in _KIND_TO_SECTION:
        raise ValueError(f"kind debe ser 'fondo' o 'activo', recibido: {kind!r}")
    catalog = catalog or load_semantic_catalog()
    section = _KIND_TO_SECTION[kind]
    entities = catalog.entities.get(section, {})
    synonyms = catalog.synonyms.get(section, {})
    needle = _normalize(text)

    for canonical_key in entities:
        if _normalize(canonical_key) == needle:
            return canonical_key

    for canonical_key, alias_list in synonyms.items():
        for alias in alias_list:
            if _normalize(alias) == needle:
                return canonical_key

    return None
