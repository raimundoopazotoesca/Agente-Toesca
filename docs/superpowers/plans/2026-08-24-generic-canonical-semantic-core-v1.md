# Generic Canonical Semantic Core v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make governed analytics execute generic, metadata-defined semantic queries with canonical identity and traceable quantitative evidence.

**Architecture:** Actions are compatibility adapters to a provider-neutral `SemanticQuery`; the executor resolves definitions and source strategies from catalog metadata. Existing synthesis and coverage guards remain fail-closed while accepting aggregate evidence as an exact structured claim.

**Tech Stack:** Python 3.11, dataclasses, YAML, SQLite read-only sandbox, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-generic-canonical-semantic-core-v1-design.md`

## Global Constraints

- The database is read-only: no migration or physical DB change.
- Do not modify UI or prompt strings.
- Preserve existing WIP; stage only files listed in each commit.
- Do not add metric/entity-specific branches to the executor or actions.
- Preserve canonical, coverage, and provenance guards as fail-closed.

---

### Task 1: Define provider-neutral semantic contracts

**Files:**
- Modify: `tools/analytics/models.py`
- Test: `tests/analytics/test_semantic_contracts.py`

- [ ] Write failing tests for a typed `SemanticQuery`, a `MetricDefinition` with metric nature/units/aggregation/source strategy, and an `EntityDefinition` with typed aliases.
- [ ] Run `python -X utf8 -m pytest tests/analytics/test_semantic_contracts.py -v` and verify the contracts are absent.
- [ ] Add immutable dataclasses and enums without SQLite or action dependencies; retain compatibility aliases for existing catalog consumers.
- [ ] Re-run the test and commit only the models and test.

### Task 2: Make metric and entity metadata authoritative

**Files:**
- Modify: `tools/analytics/catalog.py`, `tools/analytics/catalog_v1.yaml`, `semantic/entities.yaml`
- Create: `tools/entities/definitions.py`
- Test: `tests/analytics/test_catalog.py`, `tests/entities/test_definitions.py`

- [ ] Write failing tests for source-authority ambiguity lint, metadata-defined NOI/LTV/vacancy/fourth metric and typed alias resolution.
- [ ] Run focused tests and verify failure because metadata/contracts are incomplete.
- [ ] Parse and validate generic definitions; reject duplicate canonical sources; extend entity metadata with aliases without reading `derived_kpi` to enumerate identities.
- [ ] Re-run focused tests and commit only catalog/entity-definition files and tests.

### Task 3: Execute SemanticQuery generically

**Files:**
- Modify: `tools/analytics/executor.py`
- Test: `tests/analytics/test_semantic_executor.py`, `tests/analytics/test_executor_asset_scope.py`

- [ ] Write failing generic fixture tests: synthetic monthly flow range + SUM; synthetic point-in-time + SUM rejection; metadata-only fourth metric; invalid aggregation rejection.
- [ ] Run focused tests and verify the current executor rejects aggregation.
- [ ] Refactor executor to resolve source strategy, validate all semantic fields, execute read-only source access, aggregate only per definition, determine period coverage, and attach governed lineage.
- [ ] Keep `AnalyticsQueryRequest` as a compatibility adapter producing `SemanticQuery`; re-run focused tests and commit.

### Task 4: Adapt Analyst actions and evidence

**Files:**
- Modify: `tools/analyst_runtime/actions.py`, `tools/analyst_runtime/coverage_guard.py`
- Test: `tests/analyst_runtime/test_analytics_tool_contract.py`, `tests/analyst_runtime/test_quantitative_evidence.py`

- [ ] Write failing tests showing actions pass aggregation/range generically and an aggregate cannot be rendered without exact `ToolEvidence` binding.
- [ ] Run focused tests and verify current tool evidence lacks aggregate semantic metadata.
- [ ] Translate action requests into semantic queries; emit exact aggregate facts with metric, entity, range, units, coverage and lineage. Extend the guard only to bind this generic fact form, retaining rejection of unbound figures.
- [ ] Re-run focused tests and commit.

### Task 5: Canonical aliases and runtime regressions

**Files:**
- Modify: `tools/entities/resolver.py` only if required to consume definitions
- Test: `tests/analyst_runtime/test_entity_resolution_barrier.py`, `tests/analyst_runtime/test_governed_analytics_wiring.py`, `tests/analyst_runtime/test_semantic_regressions.py`

- [ ] Write failing regressions for Apoquindo typed as fund, NOI PT/TRI/Apo 2025, Viña Centro June 2026, LTV/vacancy TRI June 2026 and the clarification continuation.
- [ ] Implement only generic definition consumption and evidence-preserving continuation needed for tests.
- [ ] Run focused runtime tests and commit.

### Task 6: Freeze and execute semantic evaluation

**Files:**
- Create: `eval/semantic_holdout_v1.yaml`, `tests/analytics/test_semantic_holdout_v1.py`
- [ ] Write 8–12 cases before code freeze: flow monthly/annual, point-in-time, ratio, fund/asset, comparison/range, invalid aggregation, ambiguity, explicit type and missing period.
- [ ] Run the complete semantic/analytics/runtime suites plus holdout; record all cases, including failures.
- [ ] Fix only demonstrated implementation bugs; re-run every affected suite.

### Task 7: Product and Alpha verification

**Files:**
- Create: `eval/results/generic_canonical_semantic_core_v1.md`
- [ ] Execute provider-real smoke cases and record tools, evidence and guards for every required question.
- [ ] Execute one existing Alpha regression without prompts changes and record its result.
- [ ] Verify DB checksum/status unchanged and `git diff -- memory/agente_toesca_v2.db` remains the pre-existing WIP only.
- [ ] Commit implementation and tests in explicit file groups; never use bulk staging or push.
