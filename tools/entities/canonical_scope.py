"""Deterministic, non-fuzzy scope validation and expected-universe derivation.

Distinct from `EntityResolver` (resolver.py): that module does fuzzy/token
matching over free-text queries and returns ranked candidates. This module
does exact-key lookups against the same governed dimensions (`dim_fondo`,
`dim_activo`) for callers that already hold a canonical key and need to (a)
confirm it exists without ambiguity, or (b) derive the deterministic set of
assets a fund covers as of a given period, honoring `dim_activo.vigente_hasta`
(NULL = vigente indefinidamente; a value = last applicable period, see
migration 050_dim_activo_vigente_hasta.sql).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScopeValidation:
    valid: bool
    scope_kind: str  # "fund" | "asset"
    scope_key: str | None


class CanonicalScopeValidator:
    """Exact-match lookup against dim_fondo / dim_activo. No fuzzy matching,
    no disambiguation -- a canonical key either exists or it doesn't."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)

    def validate_fund(self, fund_key: str) -> ScopeValidation:
        conn = self._connect()
        try:
            row = conn.execute("SELECT fondo_key FROM dim_fondo WHERE fondo_key=?", (fund_key,)).fetchone()
        finally:
            conn.close()
        return ScopeValidation(row is not None, "fund", fund_key if row else None)

    def validate_asset(self, asset_key: str) -> ScopeValidation:
        conn = self._connect()
        try:
            row = conn.execute("SELECT activo_key FROM dim_activo WHERE activo_key=?", (asset_key,)).fetchone()
        finally:
            conn.close()
        return ScopeValidation(row is not None, "asset", asset_key if row else None)


@dataclass(frozen=True)
class UniverseResult:
    status: str  # "determined" | "undetermined"
    eligible_keys: frozenset[str]


def expected_asset_universe(db_path: Path, fund_key: str, period: str) -> UniverseResult:
    """The deterministic set of `activo_key` belonging to `fund_key` and
    applicable as of `period` (YYYY-MM). An asset is applicable when
    `vigente_hasta IS NULL` (vigente indefinidamente) or `vigente_hasta >=
    period` (still within its last applicable period). Returns
    status="undetermined" only if the fund itself does not resolve to any row
    in dim_activo/dim_fondo relation (i.e. the relation is not queryable for
    this key) -- callers are responsible for confirming `fund_key` is
    canonical first (see CanonicalScopeValidator.validate_fund)."""
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        fund_row = conn.execute("SELECT fondo_key FROM dim_fondo WHERE fondo_key=?", (fund_key,)).fetchone()
        if fund_row is None:
            return UniverseResult("undetermined", frozenset())
        rows = conn.execute(
            "SELECT activo_key, vigente_hasta FROM dim_activo WHERE fondo_key=?", (fund_key,)
        ).fetchall()
    finally:
        conn.close()
    eligible = frozenset(
        activo_key for activo_key, vigente_hasta in rows
        if vigente_hasta is None or vigente_hasta >= period
    )
    return UniverseResult("determined", eligible)
