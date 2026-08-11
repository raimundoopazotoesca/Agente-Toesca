"""Deterministic resolution of Spanish temporal phrases to YYYY-MM periods.

No LLM calls. Business definitions (via semantic/metrics/*.yaml `time_behavior`)
can shift the meaning of phrases like "hoy" or "último cierre" between a
month-end snapshot and an accumulated-flow window — callers pass the
resolved metric's `time_behavior` ("snapshot" | "flow" | None) when known.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass
class TemporalResolution:
    period: str | None = None
    period_range: tuple[str, str] | None = None
    comparison_period: str | None = None
    label: str = ""
    data_gap_warning: str | None = None


def _fmt(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(total, 12)
    return date(year, month0 + 1, 1)


_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\beste\s+mes\b", re.IGNORECASE), "este_mes"),
    (re.compile(r"\bmes\s+pasado\b|\bmes\s+anterior\b", re.IGNORECASE), "mes_pasado"),
    (re.compile(r"\by(?:tD)?td\b", re.IGNORECASE), "ytd"),
    (re.compile(r"\beste\s+a[ñn]o\b|\ba[ñn]o\s+actual\b", re.IGNORECASE), "este_anio"),
    (
        re.compile(
            r"\bmismo\s+per[ií]odo\s+(del\s+)?a[ñn]o\s+anterior\b|\bversus\s+a[ñn]o\s+pasado\b|"
            r"\by\s+el\s+a[ñn]o\s+pasado\b",
            re.IGNORECASE,
        ),
        "mismo_periodo_anio_anterior",
    ),
    (re.compile(r"\ba[ñn]o\s+pasado\b|\ba[ñn]o\s+anterior\b", re.IGNORECASE), "anio_pasado"),
    (re.compile(r"\b[uú]ltimos\s+12\s+meses\b|\bu12m\b", re.IGNORECASE), "u12m"),
    (re.compile(r"\bpr[óo]ximos\s+12\s+meses\b", re.IGNORECASE), "proximos_12m"),
    (re.compile(r"\b[uú]ltimo\s+cierre\b", re.IGNORECASE), "ultimo_cierre"),
    (re.compile(r"\bhoy\b", re.IGNORECASE), "hoy"),
]


def resolve_temporal(
    text: str,
    today: date | None = None,
    time_behavior: str | None = None,
) -> TemporalResolution | None:
    """Returns None if `text` contains no recognized temporal phrase.

    Known limitation: only the FIRST matching pattern in `_PATTERNS` is
    returned. A question with multiple temporal phrases (e.g. "vacancia este
    mes vs el año pasado") resolves only the first match and silently drops
    the rest -- comparison phrases after the first match are not detected.
    """
    today = today or date.today()

    matched = None
    for pattern, key in _PATTERNS:
        if pattern.search(text):
            matched = key
            break
    if matched is None:
        return None

    anchor = date(today.year, today.month, 1)

    if matched == "este_mes":
        return TemporalResolution(period=_fmt(anchor), label=f"este mes ({_fmt(anchor)})")

    if matched == "mes_pasado":
        p = _shift_months(anchor, -1)
        return TemporalResolution(period=_fmt(p), label=f"mes pasado ({_fmt(p)})")

    if matched == "este_anio":
        return TemporalResolution(
            period_range=(f"{anchor.year}-01", f"{anchor.year}-12"),
            label=f"año actual ({anchor.year})",
        )

    if matched == "ytd":
        return TemporalResolution(
            period_range=(f"{anchor.year}-01", _fmt(anchor)),
            label=f"YTD ({anchor.year}-01 a {_fmt(anchor)})",
        )

    if matched == "anio_pasado":
        y = anchor.year - 1
        return TemporalResolution(period_range=(f"{y}-01", f"{y}-12"), label=f"año pasado ({y})")

    if matched == "mismo_periodo_anio_anterior":
        return TemporalResolution(
            comparison_period="same_period_last_year",
            label="mismo período del año anterior",
        )

    if matched == "u12m":
        start = _shift_months(anchor, -11)
        return TemporalResolution(
            period_range=(_fmt(start), _fmt(anchor)),
            label=f"últimos 12 meses ({_fmt(start)} a {_fmt(anchor)})",
        )

    if matched == "proximos_12m":
        start = _shift_months(anchor, 1)
        end = _shift_months(anchor, 12)
        return TemporalResolution(
            period_range=(_fmt(start), _fmt(end)),
            label=f"próximos 12 meses ({_fmt(start)} a {_fmt(end)})",
            data_gap_warning=(
                "La base de datos contiene datos históricos, no proyecciones; "
                "este rango probablemente no tenga datos."
            ),
        )

    if matched == "ultimo_cierre":
        if time_behavior == "snapshot":
            return TemporalResolution(period=_fmt(anchor), label=f"último cierre ({_fmt(anchor)})")
        return TemporalResolution(
            period=None,
            label="último dato disponible (usar MAX(periodo) en la consulta, no asumir un mes)",
        )

    if matched == "hoy":
        if time_behavior == "flow":
            return TemporalResolution(
                period=None,
                label="hoy → para una métrica acumulada, usar el mes en curso hasta la fecha",
            )
        return TemporalResolution(period=_fmt(anchor), label=f"hoy / cierre del mes en curso ({_fmt(anchor)})")

    return None
