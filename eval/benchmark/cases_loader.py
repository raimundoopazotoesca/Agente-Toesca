"""Load and validate benchmark cases.

JSON Schema covers shape. This module adds the cross-field rules a schema
cannot express: fact refs must resolve, ids must be unique and match their
suite, holdout cases must live under cases/holdout/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import jsonschema
import yaml

BENCHMARK_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BENCHMARK_DIR / "schema" / "case.schema.json"
CASES_DIR = BENCHMARK_DIR / "cases"

_SUITE_PREFIX = {"analyst": "tae", "conversation": "tce"}


class CaseValidationError(Exception):
    """Raised when a case file violates the schema or the cross-field rules."""


@dataclass
class Case:
    id: str
    suite: str
    split: str
    turns: list[dict[str, Any]]
    path: Path
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def level(self) -> str | None:
        return self.raw.get("level")

    @property
    def tier(self) -> str | None:
        return self.raw.get("tier")

    @property
    def category(self) -> str | None:
        return self.raw.get("category")

    @property
    def capability(self) -> str | None:
        return self.raw.get("capability")

    @property
    def human_only(self) -> bool:
        return bool(self.raw.get("human_only", False))

    @property
    def ground_truth_refs(self) -> dict[str, dict[str, Any]]:
        return self.raw.get("ground_truth_refs", {})


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _iter_case_files(root: Path) -> Iterator[Path]:
    yield from sorted(p for p in root.rglob("*.yaml") if not p.name.startswith("_"))


def _fact_refs(turn: dict[str, Any]) -> list[str]:
    refs = [f["ref"] for f in turn.get("required_facts", [])]
    refs += [f["ref"] for f in turn.get("acceptable_facts", [])]
    return refs


def _check_semantics(case: Case) -> None:
    """Cross-field rules the JSON Schema cannot express."""
    prefix = _SUITE_PREFIX[case.suite]
    if not case.id.startswith(prefix + "-"):
        raise CaseValidationError(
            f"{case.path.name}: id {case.id!r} does not match suite {case.suite!r} (expected {prefix}-*)"
        )

    if case.suite == "analyst":
        if not case.level:
            raise CaseValidationError(f"{case.id}: analyst cases need a `level`")
        if not case.tier:
            raise CaseValidationError(f"{case.id}: analyst cases need a `tier`")
    else:
        if not case.category:
            raise CaseValidationError(f"{case.id}: conversation cases need a `category`")

    # Holdout lives in its own directory so the anti-leak test has one place
    # to guard, and so nobody runs it by accident during tuning.
    in_holdout_dir = "holdout" in case.path.parts
    if case.split == "holdout" and not in_holdout_dir:
        raise CaseValidationError(f"{case.id}: split=holdout but file is not under cases/holdout/")
    if case.split == "dev" and in_holdout_dir:
        raise CaseValidationError(f"{case.id}: file is under cases/holdout/ but split=dev")

    known_refs = set(case.ground_truth_refs)
    for i, turn in enumerate(case.turns):
        for ref in _fact_refs(turn):
            if ref not in known_refs:
                raise CaseValidationError(
                    f"{case.id} turn {i}: fact ref {ref!r} has no entry in ground_truth_refs"
                )
        primary = turn.get("primary_fact")
        if primary is not None:
            required = {f["ref"] for f in turn.get("required_facts", [])}
            if primary not in required:
                raise CaseValidationError(
                    f"{case.id} turn {i}: primary_fact {primary!r} is not among required_facts"
                )


def load_case(path: Path, schema: dict[str, Any] | None = None) -> Case:
    schema = schema or load_schema()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CaseValidationError(f"{path.name}: expected a YAML mapping")
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise CaseValidationError(f"{path.name}: {location}: {exc.message}") from exc

    case = Case(
        id=data["id"],
        suite=data["suite"],
        split=data["split"],
        turns=data["turns"],
        path=path,
        raw=data,
    )
    _check_semantics(case)
    return case


def load_cases(root: Path | None = None, split: str | None = None) -> list[Case]:
    """Load every case under `root`, failing loudly on the first bad file.

    `split` filters the result; it does not skip validation, so a broken
    holdout case still fails a dev-only run.
    """
    root = root or CASES_DIR
    if not root.exists():
        return []
    schema = load_schema()
    cases = [load_case(p, schema) for p in _iter_case_files(root)]

    seen: dict[str, Path] = {}
    for case in cases:
        if case.id in seen:
            raise CaseValidationError(f"duplicate case id {case.id!r}: {seen[case.id]} and {case.path}")
        seen[case.id] = case.path

    if split:
        cases = [c for c in cases if c.split == split]
    return cases
