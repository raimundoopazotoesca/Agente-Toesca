"""Match entities/periods mentioned in an answer's text against a case's
expectations, using the project's own semantic catalog (semantic/) as the
alias source instead of hardcoding names here.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SEMANTIC_DIR = Path(__file__).resolve().parents[3] / "semantic"


def _fold(text: str) -> str:
    """Lowercase, strip accents. Makes 'Viña' == 'Vina' for matching."""
    normalized = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    return without_accents.lower()


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    entities = yaml.safe_load((SEMANTIC_DIR / "entities.yaml").read_text(encoding="utf-8"))
    synonyms = yaml.safe_load((SEMANTIC_DIR / "synonyms.yaml").read_text(encoding="utf-8"))
    return {"entities": entities, "synonyms": synonyms}


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, dict[str, set[str]]]:
    """{'fondo': {'PT': {folded aliases...}}, 'activo': {...}, 'sociedad': {...}}"""
    cat = _catalog()
    index: dict[str, dict[str, set[str]]] = {"fondo": {}, "activo": {}, "sociedad": {}}

    for key, spec in cat["entities"].get("fondos", {}).items():
        aliases = {key, spec.get("nombre", "")}
        index["fondo"][key] = {_fold(a) for a in aliases if a}
    for key, aliases in cat["synonyms"].get("fondos", {}).items():
        index["fondo"].setdefault(key, set()).update(_fold(a) for a in aliases)

    for key, spec in cat["entities"].get("activos", {}).items():
        aliases = {key, spec.get("nombre", "")}
        index["activo"][key] = {_fold(a) for a in aliases if a}
    for key, aliases in cat["synonyms"].get("activos", {}).items():
        index["activo"].setdefault(key, set()).update(_fold(a) for a in aliases)

    for key, spec in cat["entities"].get("sociedades", {}).items():
        aliases = {key, spec.get("nombre", "")}
        index["sociedad"][key] = {_fold(a) for a in aliases if a}

    return index


def entity_mentioned(text: str, entity_type: str, entity_key: str) -> bool:
    """Whole-word(ish) match of any known alias of `entity_key` in `text`."""
    aliases = _alias_index().get(entity_type, {}).get(entity_key, set())
    folded = _fold(text)
    for alias in aliases:
        if not alias:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        if re.search(pattern, folded):
            return True
    return False


def other_entities_mentioned(text: str, entity_type: str, exclude_key: str) -> set[str]:
    """Keys of the same entity_type, other than exclude_key, whose aliases
    appear in text. Used for entity-confusion detection (gate F2)."""
    hits = set()
    for key in _alias_index().get(entity_type, {}):
        if key == exclude_key:
            continue
        if entity_mentioned(text, entity_type, key):
            hits.add(key)
    return hits


def check_expected_entities(text: str, expected_entities: dict[str, str]) -> dict[str, bool]:
    """{entity_type: found?} for each key in expected_entities."""
    return {
        etype: entity_mentioned(text, etype, ekey)
        for etype, ekey in (expected_entities or {}).items()
    }


_PERIOD_RE = re.compile(r"\b(20\d{2})[-/](0[1-9]|1[0-2])\b")

_MONTHS = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}
_MONTH_YEAR_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(?:de\s+)?(20\d{2})\b"
)


def periods_mentioned(text: str) -> set[str]:
    """Every YYYY-MM found in text, from either 'YYYY-MM' or 'mes YYYY'."""
    found = {f"{y}-{m}" for y, m in _PERIOD_RE.findall(text or "")}
    for month_name, year in _MONTH_YEAR_RE.findall(_fold(text or "")):
        found.add(f"{year}-{_MONTHS[month_name]}")
    return found


def period_matches(text: str, expected_period: dict[str, str]) -> bool:
    """True if the expected period (exact, or overlapping a from/to range)
    is among the periods mentioned in text. No periods requested -> True."""
    if not expected_period:
        return True
    mentioned = periods_mentioned(text)
    if not mentioned:
        return False
    if "exact" in expected_period:
        return expected_period["exact"] in mentioned
    lo = expected_period.get("from")
    hi = expected_period.get("to")
    return any((lo is None or p >= lo) and (hi is None or p <= hi) for p in mentioned)
