"""Extract numbers from an answer's markdown text, Chilean-formatted or not.

Per CLAUDE.md: "1.234.567" -> 1234567.0 (dots = thousands, no decimals),
"1.234,56" -> 1234.56 (dot = thousands, comma = decimal). Answers may also
contain plain English-style numbers (from a model that didn't localize),
so both are recognized.
"""
from __future__ import annotations

import re

# Order matters: try the more specific (thousands+decimal) forms first so a
# greedy match doesn't truncate them.
_PATTERNS = [
    r"-?\d{1,3}(?:\.\d{3})+,\d+",   # 1.234.567,89
    r"-?\d{1,3}(?:,\d{3})+\.\d+",   # 1,234,567.89
    r"-?\d{1,3}(?:\.\d{3})+",       # 1.234.567
    r"-?\d{1,3}(?:,\d{3})+",        # 1,234,567
    r"-?\d+,\d+",                   # 1234,56
    r"-?\d+\.\d+",                  # 1234.56
    r"-?\d+",                       # 1234
]
_NUMBER_RE = re.compile("|".join(_PATTERNS))


def _to_float(token: str) -> float | None:
    has_dot = "." in token
    has_comma = "," in token
    try:
        if has_dot and has_comma:
            # whichever separator comes last is the decimal one
            if token.rfind(",") > token.rfind("."):
                return float(token.replace(".", "").replace(",", "."))
            return float(token.replace(",", ""))
        if has_comma:
            # single comma group: decimal if 1-2 digits follow, else thousands
            whole, _, frac = token.partition(",")
            if len(frac) in (1, 2):
                return float(token.replace(",", "."))
            return float(token.replace(",", ""))
        if has_dot:
            whole, _, frac = token.partition(".")
            if len(frac) in (1, 2) and token.count(".") == 1:
                return float(token)
            return float(token.replace(".", ""))
        return float(token)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[float]:
    out = []
    for match in _NUMBER_RE.finditer(text or ""):
        value = _to_float(match.group(0))
        if value is not None:
            out.append(value)
    return out


def value_in_text(value: float, text: str, tolerance_pct: float = 0.0, tolerance_abs: float = 0.0) -> bool:
    """True if some number in `text` matches `value` within tolerance.

    Uses whichever tolerance is wider when both are given; a caller with no
    tolerance at all gets exact float match (rare and usually a case-authoring
    smell, but not forbidden for counts/booleans-as-0-1).
    """
    candidates = extract_numbers(text)
    for candidate in candidates:
        if tolerance_abs and abs(candidate - value) <= tolerance_abs:
            return True
        if tolerance_pct:
            allowed = abs(value) * (tolerance_pct / 100.0)
            if abs(candidate - value) <= allowed:
                return True
        if not tolerance_abs and not tolerance_pct and candidate == value:
            return True
    return False
