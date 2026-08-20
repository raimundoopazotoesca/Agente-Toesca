# F4 Governed Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated product-regression evaluator and a strict, versioned metric contract without changing runtime behavior.

**Architecture:** `eval/product_alpha` loads compact YAML cases and grades supplied trial evidence offline. `tools/analytics` loads immutable, structured metric definitions from a separate YAML catalog. Both packages are disconnected from the agent, legacy semantic catalog, benchmark, and DB writes.

**Tech Stack:** Python 3.12, dataclasses, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-f4-governed-analytics-design.md`

## Global Constraints

- Do not modify runtime, prompts, ActionRegistry, benchmark, HTTP, or database schema.
- Do not call providers or write `memory/agente_toesca_v2.db`.
- Preserve the pre-existing dirty files and stage exact files only.
- Do not create `analytics_query`; raw SQL remains outside the new catalog.

### Task 1: Alpha Product Eval data contract and cases

**Files:**
- Create: `eval/product_alpha/__init__.py`, `eval/product_alpha/models.py`, `eval/product_alpha/cases.py`, `eval/product_alpha/cases/*.yaml`
- Test: `eval/product_alpha/tests/test_cases.py`

**Interfaces:**
- Produces `load_cases(root: Path | None = None) -> list[ProductCase]`.
- Produces `ProductCase` with `id`, `turns`, constraints, capabilities, and tags.

- [ ] Write tests for valid A–H cases, duplicate IDs, and malformed case fields.
- [ ] Run `python -X utf8 -m pytest eval/product_alpha/tests/test_cases.py -q` and observe failure because the package does not exist.
- [ ] Implement dataclasses, YAML loader, cross-case uniqueness validation, and eight outcome-first case files.
- [ ] Re-run the focused tests and confirm success.

### Task 2: Alpha Product Eval offline graders

**Files:**
- Create: `eval/product_alpha/graders.py`, `eval/product_alpha/runner.py`
- Test: `eval/product_alpha/tests/test_graders.py`

**Interfaces:**
- Consumes `ProductCase` and `TrialEvidence`.
- Produces `EvaluationResult` with one pass/fail outcome per configured deterministic constraint.

- [ ] Write tests for accepted canonical numeric value, rejected alternative value, entity mentions, forbidden claim/labels, available capability, and multiple independent trials.
- [ ] Run `python -X utf8 -m pytest eval/product_alpha/tests/test_graders.py -q` and observe failure because graders do not exist.
- [ ] Implement pure offline grading over supplied response text, capabilities, and metadata; do not invoke tools or providers.
- [ ] Re-run the focused suite and confirm success.
- [ ] Stage only Stage 0.5 files plus this design/plan and commit `eval(alpha): add product regression skeleton`.

### Task 3: Typed governed metric catalog

**Files:**
- Create: `tools/analytics/__init__.py`, `tools/analytics/models.py`, `tools/analytics/catalog.py`, `tools/analytics/catalog_v1.yaml`
- Test: `tests/analytics/test_catalog.py`

**Interfaces:**
- Produces `load_metric_catalog(path: Path | None = None) -> MetricCatalog`.
- Produces immutable `MetricDefinition` and structured `DerivedKpiAccess` / `ViewMetricAccess` values.

- [ ] Write tests that load the three definitions and assert distinct keys, sources, grains, units, aggregation behavior, relations, deterministic ordering, and absence of values/entities.
- [ ] Run `python -X utf8 -m pytest tests/analytics/test_catalog.py -q` and observe failure because the package does not exist.
- [ ] Implement typed YAML parsing and immutable catalog serialization.
- [ ] Re-run the focused tests and confirm success.

### Task 4: Catalog negative validation and isolated regressions

**Files:**
- Modify: `tests/analytics/test_catalog.py`

**Interfaces:**
- `CatalogValidationError` identifies duplicate keys, unsupported enum/grain, malformed access, unknown relation, and prohibited value-bearing fields.

- [ ] Write temporary YAML fixture tests for each invalid configuration path.
- [ ] Run those tests and observe their expected failure before validation exists.
- [ ] Implement fail-fast validation with no fallback to `semantic/`.
- [ ] Run new suites, required existing regression suites, DB SHA check, fingerprint checks, and `git diff --cached --name-status`.
- [ ] Stage only catalog files and commit `feat(analytics): add governed metric catalog`.
