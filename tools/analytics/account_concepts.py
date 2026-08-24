"""Data-driven, read-only account-concept queries over operational ER lines.

The catalog is the authority for source matching.  It intentionally uses only
exact source codes/names -- never runtime keyword or LIKE matching.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CATALOG_PATH = Path(__file__).with_name("account_concepts_v1.yaml")


class AccountQueryError(ValueError):
    pass


@dataclass(frozen=True)
class SourceAccountMapping:
    concept_id: str
    status: str
    code: str | None = None
    name: str | None = None
    asset: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    sign_rule: str | None = None
    allocation: float = 1.0
    unit: str = "clp"
    amount_field: str = "monto_clp"
    note: str | None = None


@dataclass(frozen=True)
class AccountConceptDefinition:
    concept_id: str
    display_name: str
    aliases: tuple[str, ...]
    basis: str
    nature: str
    units: tuple[str, ...]
    allowed_aggregations: tuple[str, ...]
    entity_types: tuple[str, ...]
    mappings: tuple[SourceAccountMapping, ...]


class AccountConceptCatalog:
    def __init__(self, concepts: dict[str, AccountConceptDefinition]):
        self._concepts = concepts
        self._aliases = {alias.casefold(): concept for concept in concepts.values() for alias in (concept.concept_id, *concept.aliases)}

    @classmethod
    def load(cls, path: Path | None = None) -> "AccountConceptCatalog":
        return cls.from_dict(yaml.safe_load((path or CATALOG_PATH).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AccountConceptCatalog":
        if not isinstance(raw, dict) or not isinstance(raw.get("concepts"), list):
            raise AccountQueryError("malformed account concept catalog")
        concepts: dict[str, AccountConceptDefinition] = {}
        for item in raw["concepts"]:
            required = {"concept_id", "display_name", "aliases", "basis", "nature", "units", "allowed_aggregations", "entity_types", "mappings"}
            if not isinstance(item, dict) or required - item.keys() or item["concept_id"] in concepts:
                raise AccountQueryError("malformed account concept definition")
            mappings = tuple(SourceAccountMapping(
                concept_id=str(mapping.get("concept_id", item["concept_id"])), status=str(mapping.get("status", "mapped")),
                code=mapping.get("code"), name=mapping.get("name"), asset=mapping.get("asset"),
                valid_from=mapping.get("valid_from"), valid_to=mapping.get("valid_to"), sign_rule=mapping.get("sign_rule"),
                allocation=float(mapping.get("allocation", 1.0)), unit=str(mapping.get("unit", "clp")), amount_field=str(mapping.get("amount_field", "monto_clp")), note=mapping.get("note"),
            ) for mapping in item["mappings"])
            if any(mapping.concept_id != item["concept_id"] or mapping.status not in {"mapped", "unmapped", "ambiguous", "excluded"} or (mapping.code is None and mapping.name is None) for mapping in mappings):
                raise AccountQueryError("malformed source account mapping")
            concepts[item["concept_id"]] = AccountConceptDefinition(
                concept_id=str(item["concept_id"]), display_name=str(item["display_name"]), aliases=tuple(str(v) for v in item["aliases"]),
                basis=str(item["basis"]), nature=str(item["nature"]), units=tuple(str(v) for v in item["units"]),
                allowed_aggregations=tuple(str(v) for v in item["allowed_aggregations"]), entity_types=tuple(str(v) for v in item["entity_types"]), mappings=mappings,
            )
        return cls(concepts)

    def get(self, concept_id: str) -> AccountConceptDefinition:
        try:
            return self._concepts[concept_id]
        except KeyError as exc:
            raise AccountQueryError(f"unknown account concept: {concept_id}") from exc

    def resolve_alias(self, term: str) -> AccountConceptDefinition:
        try:
            return self._aliases[term.casefold()]
        except KeyError as exc:
            raise AccountQueryError(f"unknown account concept alias: {term}") from exc


@dataclass(frozen=True)
class AccountQuery:
    concept_id: str
    entity_id: str
    entity_type: str
    period: str
    period_end: str | None = None
    aggregation: str | None = None


@dataclass(frozen=True)
class AccountQueryResult:
    concept_id: str
    entity_id: str
    entity_type: str
    period: str
    value: float | None
    unit: str | None
    basis: str
    coverage: dict[str, Any]
    account_row_count: int
    source_mappings: tuple[dict[str, Any], ...]
    lineage: dict[str, Any]


class AccountQueryExecutor:
    governed_sql = "SELECT ... WHERE (cuenta_codigo = ? OR cuenta_nombre = ?) -- exact mapping predicates only"

    def __init__(self, db_path: Path, catalog: AccountConceptCatalog | None = None):
        self.db_path = Path(db_path)
        self.catalog = catalog or AccountConceptCatalog.load()

    def execute(self, query: AccountQuery) -> AccountQueryResult:
        concept = self.catalog.get(query.concept_id)
        if query.entity_type not in concept.entity_types:
            raise AccountQueryError("entity type is not permitted by account concept")
        if query.aggregation and query.aggregation not in concept.allowed_aggregations:
            raise AccountQueryError("aggregation is not permitted by account concept")
        end = query.period_end or query.period
        if end < query.period:
            raise AccountQueryError("invalid period range")
        candidates = [mapping for mapping in concept.mappings if self._mapping_applies(mapping, query.entity_id, query.period, end)]
        mapped = [mapping for mapping in candidates if mapping.status == "mapped"]
        if not mapped:
            return self._none(concept, query, end)
        rows = self._fetch(query, end, candidates)
        mapped_rows = [(row, mapping) for row in rows for mapping in mapped if self._matches(row, mapping)]
        unmapped_rows = [row for row in rows if any(self._matches(row, mapping) for mapping in candidates if mapping.status in {"unmapped", "ambiguous"})]
        units = {mapping.unit for _, mapping in mapped_rows}
        if len(units) > 1:
            raise AccountQueryError("mapped rows use incompatible native units")
        values = [self._normalized(row, mapping) for row, mapping in mapped_rows]
        periods = _month_range(query.period, end)
        observed_periods = {str(row[1]) for row, _ in mapped_rows}
        status = "complete" if len(observed_periods) == len(periods) and not unmapped_rows else ("partial" if mapped_rows else "none")
        return AccountQueryResult(
            concept.concept_id, query.entity_id, query.entity_type, f"{query.period}..{end}" if end != query.period else query.period,
            sum(values) if values else None, next(iter(units), None), concept.basis,
            {"status": status, "expected_periods": periods, "observed_periods": sorted(observed_periods), "mapped_row_count": len(mapped_rows), "unmapped_row_count": len(unmapped_rows)},
            len(mapped_rows), tuple(_mapping_dict(mapping) for mapping in sorted({mapping for _, mapping in mapped_rows}, key=lambda item: (item.code or "", item.name or ""))),
            {"table": "raw_er_activo_line", "current_only": True, "source_files": sorted({row[7] for row, _ in mapped_rows if row[7]}), "ingest_run_ids": sorted({row[11] for row, _ in mapped_rows if row[11] is not None})},
        )

    @staticmethod
    def _mapping_applies(mapping: SourceAccountMapping, entity: str, start: str, end: str) -> bool:
        return (mapping.asset in (None, entity) and (mapping.valid_from is None or mapping.valid_from <= end) and (mapping.valid_to is None or mapping.valid_to >= start))

    def _fetch(self, query: AccountQuery, end: str, mappings: list[SourceAccountMapping]) -> list[tuple]:
        clauses, params = [], [query.entity_id, query.period, end]
        for mapping in mappings:
            if mapping.code is not None:
                clauses.append("cuenta_codigo = ?"); params.append(mapping.code)
            else:
                clauses.append("cuenta_nombre = ?"); params.append(mapping.name)
        sql = ("SELECT cuenta_codigo, periodo, cuenta_nombre, monto_clp, monto_uf, source_sheet, source_row, source_file, file_hash, ingest_run_id, superseded_at, ingest_run_id "
               "FROM raw_er_activo_line WHERE activo_key=? AND periodo BETWEEN ? AND ? AND superseded_at IS NULL AND (" + " OR ".join(clauses) + ")")
        with sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True) as conn:
            conn.execute("PRAGMA query_only=ON")
            return conn.execute(sql, params).fetchall()

    @staticmethod
    def _matches(row: tuple, mapping: SourceAccountMapping) -> bool:
        return (mapping.code is not None and row[0] == mapping.code) or (mapping.code is None and row[2] == mapping.name)

    @staticmethod
    def _normalized(row: tuple, mapping: SourceAccountMapping) -> float:
        raw = row[3] if mapping.amount_field == "monto_clp" else row[4]
        if raw is None:
            raise AccountQueryError("mapped row is missing its declared native amount")
        if mapping.sign_rule != "expense_magnitude":
            raise AccountQueryError("mapped account lacks deterministic sign rule")
        return abs(float(raw)) * mapping.allocation

    @staticmethod
    def _none(concept: AccountConceptDefinition, query: AccountQuery, end: str) -> AccountQueryResult:
        return AccountQueryResult(concept.concept_id, query.entity_id, query.entity_type, f"{query.period}..{end}", None, None, concept.basis, {"status": "none", "expected_periods": _month_range(query.period, end), "observed_periods": [], "mapped_row_count": 0, "unmapped_row_count": 0}, 0, (), {"table": "raw_er_activo_line", "current_only": True})


def _mapping_dict(mapping: SourceAccountMapping) -> dict[str, Any]:
    return {"code": mapping.code, "name": mapping.name, "asset": mapping.asset, "sign_rule": mapping.sign_rule, "allocation": mapping.allocation, "unit": mapping.unit, "amount_field": mapping.amount_field, "status": mapping.status, "note": mapping.note}


def _month_range(start: str, end: str) -> list[str]:
    year, month = map(int, start.split("-")); end_year, end_month = map(int, end.split("-"))
    months = []
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months
