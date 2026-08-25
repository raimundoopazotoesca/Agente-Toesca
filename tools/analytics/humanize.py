"""Human Analytical Presentation v1 — deterministic display humanizers.

Presentation-only layer. Never mutates a protected fact (value, unit,
entity_id, period, aggregation); only changes how already-decided,
already-governed text is rendered to a reader. Driven entirely by metadata
(``dim_fondo``/``dim_activo``/``dim_sociedad`` display names, the metric/
account-concept catalogs) — there is no per-metric or per-entity branching
here, so a brand-new fund/asset/metric needs no code change, only a catalog
row.

Three independent responsibilities, composed by callers as needed:

* :func:`entity_display_name` — raw entity key -> human name.
* :func:`format_period` / :func:`format_period_range` — ``YYYY-MM`` strings
  -> natural Spanish temporal phrases.
* :func:`humanize_text` — best-effort cleanup of already-produced prose
  (model ``raw_text``/``text`` fragments) that may still contain raw
  entity keys, ``YYYY-MM..YYYY-MM`` notation, or internal jargon tokens.
  This never invents or changes a number; it only re-labels identifiers and
  reformats plain float literals it can recognise byte-for-byte.
"""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

_MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

_MESES_ABREV = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

_ENTITY_KIND_LABELS = {"fund": "Fondo", "asset": "Activo", "company": "Sociedad"}

_FORBIDDEN_JARGON = [
    "canonical_metric_ref", "governed_dataset_ref", "canonical_metric",
    "governed_dataset", "ToolEvidence", "AllowedClaim", "SemanticQuery",
    "entity_id=", "entity_key=", "coverage=", "aggregation=sum",
    "aggregation=avg", "aggregation=point_in_time", "canonical",
]


# --------------------------------------------------------------------------
# Entity display
# --------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _entity_catalog(db_path: str) -> dict[str, tuple[str, str]]:
    """Load ``{raw_key: (display_name, entity_kind)}`` from the dims.

    ``entity_kind`` is one of ``fund`` / ``asset`` / ``company``. Cached per
    db_path (the catalog is small and effectively static within a process).
    """
    catalog: dict[str, tuple[str, str]] = {}
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        for key, nombre in conn.execute("SELECT fondo_key, nombre FROM dim_fondo"):
            catalog[key] = (f"fondo {key}", "fund")
        for key, nombre in conn.execute("SELECT activo_key, nombre FROM dim_activo"):
            if nombre and nombre != key:
                catalog[key] = (nombre, "asset")
        for key, nombre in conn.execute("SELECT sociedad_key, nombre FROM dim_sociedad"):
            if key not in catalog and nombre:
                catalog[key] = (nombre, "company")
    finally:
        conn.close()
    return catalog


def entity_display_name(entity_key: Any, db_path: Path | str | None = None) -> str:
    """Human name for a raw entity key. Unknown keys pass through unchanged
    (fail-open on display only — never blocks an answer for a fact the
    system already validated)."""
    if not isinstance(entity_key, str) or db_path is None:
        return str(entity_key)
    try:
        catalog = _entity_catalog(str(db_path))
    except Exception:  # noqa: BLE001 -- display must never raise
        return entity_key
    entry = catalog.get(entity_key)
    return entry[0] if entry else entity_key


def entity_kind_label(entity_key: Any, db_path: Path | str | None = None) -> str:
    """Generic Spanish noun for the entity's kind (``"Fondo"``/``"Activo"``/
    ``"Sociedad"``), for a table's row-header column. Unknown keys or a
    missing catalog fall back to the generic ``"Entidad"`` -- display-only,
    never blocks rendering."""
    if not isinstance(entity_key, str) or db_path is None:
        return "Entidad"
    try:
        catalog = _entity_catalog(str(db_path))
    except Exception:  # noqa: BLE001 -- display must never raise
        return "Entidad"
    entry = catalog.get(entity_key)
    if entry is None:
        return "Entidad"
    return _ENTITY_KIND_LABELS.get(entry[1], "Entidad")


def _entity_catalog_safe(db_path: Path | str | None) -> dict[str, tuple[str, str]]:
    if db_path is None:
        return {}
    try:
        return _entity_catalog(str(db_path))
    except Exception:  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------
# Period display
# --------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_period(period: str) -> tuple[int, int] | None:
    match = _PERIOD_RE.match(period)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def format_period(period: str) -> str:
    """Single month, e.g. ``2026-06`` -> ``"en junio de 2026"``."""
    parsed = _parse_period(period)
    if parsed is None:
        return period
    year, month = parsed
    if month not in _MESES:
        return period
    return f"en {_MESES[month]} de {year}"


def format_period_short(period: str) -> str:
    """Compact table-header phrasing, e.g. ``2026-06`` -> ``"jun-2026"``."""
    parsed = _parse_period(period)
    if parsed is None:
        return period
    year, month = parsed
    if month not in _MESES_ABREV:
        return period
    return f"{_MESES_ABREV[month]}-{year}"


def format_period_as_of(period: str) -> str:
    """Point-in-time phrasing, e.g. for a balance/ratio observed at month end."""
    parsed = _parse_period(period)
    if parsed is None:
        return period
    year, month = parsed
    if month not in _MESES:
        return period
    return f"a {_MESES[month]} de {year}"


def format_period_range(start: str, end: str) -> str:
    """Natural phrase for a ``[start, end]`` inclusive month range.

    - Full calendar year (Jan..Dec, same year): "durante 2025"
    - Within-year partial range: "entre enero y junio de 2025"
    - Cross-year range: "entre diciembre de 2017 y enero de 2018"
    - start == end: same as :func:`format_period`
    - Unparseable input: passed through unchanged.
    """
    if start == end:
        return format_period(start)
    p_start = _parse_period(start)
    p_end = _parse_period(end)
    if p_start is None or p_end is None:
        return f"{start} a {end}"
    year_start, month_start = p_start
    year_end, month_end = p_end
    if year_start == year_end and month_start == 1 and month_end == 12:
        return f"durante {year_start}"
    if year_start == year_end:
        return f"entre {_MESES.get(month_start, month_start)} y {_MESES.get(month_end, month_end)} de {year_start}"
    return (f"entre {_MESES.get(month_start, month_start)} de {year_start} "
            f"y {_MESES.get(month_end, month_end)} de {year_end}")


# --------------------------------------------------------------------------
# Aggregation display
# --------------------------------------------------------------------------

_AGGREGATION_PHRASES = {
    "sum": "acumulado",
    "total": "acumulado",
    "avg": "promedio",
    "average": "promedio",
    "point_in_time": "",  # omit -- the period phrase already conveys "as of"
    "last": "",
    "max": "máximo",
    "min": "mínimo",
}


def format_aggregation(aggregation: Any) -> str:
    if not isinstance(aggregation, str):
        return ""
    return _AGGREGATION_PHRASES.get(aggregation, aggregation)


# --------------------------------------------------------------------------
# Free-text cleanup (raw_text / text fragments)
# --------------------------------------------------------------------------

_RANGE_RE = re.compile(r"\b(\d{4}-\d{2})\.\.(\d{4}-\d{2})\b")
_SINGLE_PERIOD_RE = re.compile(r"\b(\d{4}-\d{2})\b")
_RAW_FLOAT_RE = re.compile(r"(?<![\d.,])\d+\.\d{3,}(?![\d.,])")


def _chilean_number(value: float, precision: int = 2) -> str:
    rendered = f"{value:,.{precision}f}"
    return rendered.replace(",", "X").replace(".", ",").replace("X", ".")


def humanize_text(text: str, db_path: Path | str | None = None) -> str:
    """Best-effort, deterministic cleanup of model-authored prose fragments.

    Order matters: ranges before single periods (a range contains two valid
    single-period substrings), longest entity keys before shorter ones (so
    ``Apo4501`` is matched before the ``Apo`` prefix it starts with).
    """
    if not isinstance(text, str) or not text:
        return text

    result = text

    # 1. YYYY-MM..YYYY-MM ranges -> natural phrase.
    def _sub_range(match: "re.Match[str]") -> str:
        return format_period_range(match.group(1), match.group(2))

    result = _RANGE_RE.sub(_sub_range, result)

    # 2. Remaining bare YYYY-MM -> natural phrase.
    def _sub_single(match: "re.Match[str]") -> str:
        return format_period(match.group(1))

    result = _SINGLE_PERIOD_RE.sub(_sub_single, result)

    # 3. Raw entity keys -> display names (longest key first to avoid a
    # short key partially matching inside a longer one).
    catalog = _entity_catalog_safe(db_path)
    if catalog:
        # A single alternation pass, longest alternative first, so a raw key
        # that is itself a substring of an already-human display name the
        # model wrote out in full (e.g. asset "Boulevard PT", whose dim
        # nombre already ends in the fund key "PT") is matched and protected
        # as one unit -- not re-substituted piecemeal.
        replacements: dict[str, tuple[str, str]] = {}  # literal -> (replacement, kind)
        for key, (display_name, kind) in catalog.items():
            replacements[key] = (display_name, kind)
            replacements.setdefault(display_name, (display_name, "display_name"))
        ordered = sorted(replacements, key=len, reverse=True)
        combined = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(text) for text in ordered) + r")(?!\w)", re.UNICODE
        )

        def _sub_entity(match: "re.Match[str]") -> str:
            literal = match.group(1)
            display_name, kind = replacements[literal]
            # Avoid "el fondo fondo PT": if the model's own prose already
            # wrote "fondo "/"Fondo " right before the raw key, the display
            # name (which already carries that prefix for fund keys) would
            # duplicate it -- drop the model's word in that case.
            prefix_len = 6  # len("fondo ")
            start = match.start()
            preceding = result[max(0, start - prefix_len):start]
            if kind == "fund" and preceding.casefold().endswith("fondo "):
                return display_name[len("fondo "):]
            return display_name

        result = combined.sub(_sub_entity, result)

    # 4. Raw high-precision float literals -> Chilean-formatted 2dp numbers.
    # Only reformats digits/decimal point; never changes magnitude/sign.
    def _sub_float(match: "re.Match[str]") -> str:
        try:
            return _chilean_number(float(match.group(0)), 2)
        except ValueError:
            return match.group(0)

    result = _RAW_FLOAT_RE.sub(_sub_float, result)

    # 5. Aggregation/label tokens that leak internal vocabulary.
    for token, phrase in (
        ("sum:", "acumulado:"), ("avg:", "promedio:"), ("point_in_time:", ""),
    ):
        result = result.replace(token, phrase)

    # 6. Period phrases already carry their own preposition ("durante 2025",
    # "entre enero y junio de 2025", "a junio de 2026"); drop a redundant
    # leading preposition the model's own prose left in front of them.
    result = re.sub(r"\b[Ee]n (durante|entre)\b", lambda m: m.group(1), result)

    # 7. Markdown-escape artifacts (a model backslash-escaping punctuation to
    # dodge Markdown list/emphasis parsing, e.g. "fueron\:", "PT\.") leak the
    # backslash verbatim once rendered outside a Markdown-aware viewer. This
    # is a generic de-escape of any backslash-escaped ASCII punctuation, not a
    # fix for one character or one fragment.
    result = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~])", r"\1", result)

    return result


def strip_forbidden_jargon(text: str) -> str:
    """Defensive net: remove internal identifiers that should never reach a
    user, if one somehow survives the passes above. Used only for tests /
    guard assertions, not required for normal operation once callers route
    through :func:`humanize_text`."""
    result = text
    for token in _FORBIDDEN_JARGON:
        result = result.replace(token, "")
    return result
