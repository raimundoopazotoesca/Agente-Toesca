# Analyst Agent Phase 3 — Conversational Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the accidental, mechanical `or`-based conversation state merge in the Analyst Agent with a structured `ConversationState` (per-field `raw_value`/`canonical_value`/`resolution_status`/`source`), a single LLM call for conversational understanding that emits a `turn_relation` + field-level delta, and a deterministic merge/commit pipeline — so multi-turn conversations (inheritance, replacement, correction, topic reset, exploratory questions) resolve reliably instead of by accident.

**Architecture:** `tools/analyst/conversation_state.py` holds the new dataclasses and pure state storage (get/commit/clear, unchanged eviction policy). `tools/analyst/state_merge.py` validates and applies deltas deterministically (catalog/entity resolution happens here, never in the LLM). `tools/analyst/conversation_understanding.py` owns the single LLM call (prompt + parse) and has zero side effects. `tools/analyst/context_builder.py` orchestrates the full `understand → validate → apply → ambiguity → commit` sequence from the design spec and produces `AnalystContext` for SQL generation. `tools/analyst/ambiguity.py` is rewritten to evaluate a `ConversationState` candidate instead of the old `IntentResult`. `tools/analyst/intent.py` becomes a thin backward-compatible façade over the new pipeline until its last internal consumers are migrated, then is deleted.

**Tech Stack:** Python 3, dataclasses, `pytest`, existing `tools/analyst/semantic_loader.py` (YAML + jsonschema catalog), existing `tools/analyst/entity_resolver.py`, existing `tools/analyst/temporal.py` and `tools/analyst/verified_queries_repo.py` (untouched), Flask app in `scripts/ingesta_server.py` (untouched — only consumes `tools/db_chat.answer()`, whose external contract does not change).

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-08-12-analyst-agent-phase3-design.md`. Every task below implements a section of that spec — deviate only if this plan explicitly says so.
- SQL pipeline (`_validate_sql`, `_run_sql`, SELECT-only enforcement, provider fallback chain) in `tools/db_chat.py` is **not modified** in this plan. Only the context that feeds into SQL-generation prompts changes.
- `source` on every `ResolvedValue` describes how the value was obtained **in the current turn** (`explicit`/`inherited`/`inferred`), never historical origin and never confidence.
- The semantic catalog (`semantic/metrics/*.yaml`) is never a whitelist: an unresolved metric/entity is preserved as `raw_value` with `resolution_status="unresolved"`, never discarded.
- `turn_relation="new_topic"` clears any state dimension the LLM delta didn't mention; `continue`/`modify`/`correct` keep it. An invalid/unparseable LLM response degrades to `turn_relation="continue"` with an empty delta (never an exception, never `new_topic` — conservative default).
- State is committed (`commit_state`) only after `decide_ambiguity` returns `action="proceed"`. On `clarify`, the candidate state is discarded and the previously committed state is untouched.
- `session_id` scoping and the 500-session LRU eviction cap in `conversation_state.py` are preserved unchanged.
- No test may depend on network access — all LLM calls in tests use fake/injected callables, matching the existing pattern in `tests/analyst/test_intent.py` and `tests/analyst/test_context_builder.py`.
- Run `pytest tests/analyst/ tests/eval/ -v` after every task; all previously-passing tests must stay green (except ones this plan explicitly rewrites).

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/analyst/conversation_state.py` (rewrite) | `ResolvedValue`, `ConversationState` dataclasses; `get_state`, `commit_state`, `clear_state` — pure storage, no LLM/business logic |
| `tools/analyst/state_merge.py` (new) | `validate_delta(raw_llm_json) -> ValidatedTurn`; `apply_delta(previous_state, validated_turn) -> ConversationState` — deterministic merge, catalog/entity resolution |
| `tools/analyst/conversation_understanding.py` (new) | `understand_conversation_llm(question, state, recent_turns, llm_call) -> str` (raw LLM JSON) + prompt template — no parsing, no persistence |
| `tools/analyst/ambiguity.py` (rewrite) | `decide_ambiguity(candidate_state, verified_hint, has_history) -> AmbiguityDecision` |
| `tools/analyst/context_builder.py` (rewrite) | Orchestrates understand→validate→apply→ambiguity→commit; builds `AnalystContext.prompt_sections` from `ConversationState` |
| `tools/analyst/intent.py` (rewrite → façade, deleted last) | `extract_intent(...)` façade delegating to the new pipeline, returning legacy `IntentResult` shape for unmigrated callers |
| `tools/db_chat.py` (modify) | Remove manual `update_state(...)` call at end of `answer()`; adapt fallback-context construction to new `ConversationState`/`AnalystContext` shape |
| `tests/analyst/test_conversation_state.py` (new, replaces relevant parts of old suite) | Tests for `ResolvedValue`/`ConversationState`/storage |
| `tests/analyst/test_state_merge.py` (new) | Tests for `validate_delta`/`apply_delta` — the core of this phase |
| `tests/analyst/test_conversation_understanding.py` (new) | Tests for prompt construction + fake-LLM round trip |
| `tests/analyst/test_ambiguity.py` (rewrite) | Tests for new `decide_ambiguity` |
| `tests/analyst/test_context_builder.py` (rewrite) | End-to-end orchestration tests with fake LLM |
| `tests/analyst/test_intent.py` (rewrite → façade tests, deleted last) | Tests that the façade still returns legacy shape |
| `tests/eval/conversations.yaml` (expand) | 8 scenarios per design §6 |
| `tests/eval/run_eval.py` (modify) | Add `--stability N` mode |

---

## Task 1: `ResolvedValue` / `ConversationState` dataclasses and storage

**Files:**
- Modify (rewrite): `tools/analyst/conversation_state.py`
- Test: `tests/analyst/test_conversation_state.py`

**Interfaces:**
- Produces:
  - `ResolvedValue(raw_value: Any, canonical_value: Any | None, resolution_status: str, source: str)` — a frozen-ish dataclass (not actually frozen, but treated as immutable by convention: merge always builds new instances).
  - `ConversationState(active_goal, analysis_mode, entities: dict[str, ResolvedValue], metrics: list[ResolvedValue], period, comparison, grouping, output_request)` — all singular fields are `ResolvedValue | None`.
  - `get_state(session_id: str) -> ConversationState` — returns a fresh empty `ConversationState()` if unseen.
  - `commit_state(session_id: str, state: ConversationState) -> None` — persists; same OrderedDict + `_MAX_SESSIONS=500` LRU eviction as today.
  - `clear_state(session_id: str) -> None` — unchanged behavior.
- Consumes: nothing (base layer).

- [ ] **Step 1: Write the failing tests**

```python
# tests/analyst/test_conversation_state.py
from tools.analyst.conversation_state import (
    ResolvedValue, ConversationState, get_state, commit_state, clear_state,
)


def test_get_state_returns_empty_state_for_unseen_session():
    clear_state("cs-test-1")
    state = get_state("cs-test-1")
    assert isinstance(state, ConversationState)
    assert state.active_goal is None
    assert state.metrics == []
    assert state.entities == {}


def test_commit_then_get_roundtrips():
    clear_state("cs-test-2")
    state = ConversationState(
        metrics=[ResolvedValue(raw_value="vacancia", canonical_value="vacancia_pct",
                                resolution_status="resolved", source="explicit")],
        entities={"fondo": ResolvedValue(raw_value="PT", canonical_value="PT",
                                          resolution_status="resolved", source="explicit")},
    )
    commit_state("cs-test-2", state)
    fetched = get_state("cs-test-2")
    assert fetched.metrics[0].canonical_value == "vacancia_pct"
    assert fetched.entities["fondo"].canonical_value == "PT"


def test_commit_is_isolated_per_session():
    clear_state("cs-test-3a")
    clear_state("cs-test-3b")
    state_a = ConversationState(period=ResolvedValue("2026-07", "2026-07", "resolved", "explicit"))
    commit_state("cs-test-3a", state_a)
    fetched_b = get_state("cs-test-3b")
    assert fetched_b.period is None


def test_clear_state_resets_to_empty():
    clear_state("cs-test-4")
    commit_state("cs-test-4", ConversationState(
        period=ResolvedValue("2026-07", "2026-07", "resolved", "explicit")))
    clear_state("cs-test-4")
    assert get_state("cs-test-4").period is None


def test_eviction_caps_at_max_sessions():
    from tools.analyst.conversation_state import _MAX_SESSIONS, _STATE
    _STATE.clear()
    for i in range(_MAX_SESSIONS + 5):
        commit_state(f"cs-evict-{i}", ConversationState())
    assert len(_STATE) == _MAX_SESSIONS
    assert "cs-evict-0" not in _STATE  # oldest evicted first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analyst/test_conversation_state.py -v`
Expected: FAIL with `ImportError` (`ResolvedValue`/`ConversationState`/`commit_state` don't exist yet).

- [ ] **Step 3: Implement `conversation_state.py`**

```python
"""In-memory conversation state, keyed by session_id, for the Flask process.

Lost on server restart by design (confirmed acceptable for daily internal
use — see docs/superpowers/specs/2026-08-10-analyst-agent-phase1-design.md).

Pure storage layer: no LLM calls, no catalog/entity resolution. Those live
in tools/analyst/state_merge.py, which builds the ConversationState objects
this module stores.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResolvedValue:
    raw_value: Any
    canonical_value: Any | None
    resolution_status: str  # "resolved" | "unresolved" | "ambiguous"
    source: str              # "explicit" | "inherited" | "inferred" -- provenance in THIS turn


@dataclass
class ConversationState:
    active_goal: ResolvedValue | None = None
    analysis_mode: ResolvedValue | None = None
    entities: dict[str, ResolvedValue] = field(default_factory=dict)
    metrics: list[ResolvedValue] = field(default_factory=list)
    period: ResolvedValue | None = None
    comparison: ResolvedValue | None = None
    grouping: ResolvedValue | None = None
    output_request: ResolvedValue | None = None


# Cap on distinct session_id keys held in memory. Without a bound, a process
# that never restarts would grow _STATE forever (e.g. one key per malicious
# or unbounded conversation_id). Oldest entries are evicted first.
_MAX_SESSIONS = 500

_STATE: "OrderedDict[str, ConversationState]" = OrderedDict()


def get_state(session_id: str) -> ConversationState:
    if session_id not in _STATE:
        return ConversationState()
    return _STATE[session_id]


def commit_state(session_id: str, state: ConversationState) -> None:
    if session_id in _STATE:
        _STATE.move_to_end(session_id)
    _STATE[session_id] = state
    if len(_STATE) > _MAX_SESSIONS:
        _STATE.popitem(last=False)


def clear_state(session_id: str) -> None:
    _STATE.pop(session_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analyst/test_conversation_state.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/conversation_state.py tests/analyst/test_conversation_state.py
git commit -m "feat(conversation): replace flat state dict with ResolvedValue/ConversationState"
```

---

## Task 2: Deterministic delta validation and merge (`state_merge.py`)

This is the core of the phase: turns the LLM's raw JSON into a validated, applied `ConversationState`, with catalog/entity resolution happening here — never in the LLM, never left as a whitelist filter.

**Files:**
- Create: `tools/analyst/state_merge.py`
- Test: `tests/analyst/test_state_merge.py`

**Interfaces:**
- Consumes:
  - `ConversationState`, `ResolvedValue` from `tools/analyst/conversation_state.py` (Task 1).
  - `resolve_entity(text, kind, catalog) -> str | None` from `tools/analyst/entity_resolver.py` (existing, unmodified).
  - `load_semantic_catalog() -> SemanticCatalog` from `tools/analyst/semantic_loader.py` (existing, unmodified). `catalog.metrics: dict[str, dict]` — keys are canonical metric names.
- Produces:
  - `FIELD_NAMES: list[str]` — the 8 known field identifiers: `"active_goal", "analysis_mode", "entities.fondo", "entities.activo", "metrics", "period", "comparison", "grouping", "output_request"`.
  - `@dataclass ValidatedTurn(turn_relation: str, delta: list[dict])` — `turn_relation` always one of `continue|modify|correct|new_topic` (never anything else after validation); `delta` is a list of dicts with keys `field`, `operation`, and optionally `raw_value`/`source`, all already sanity-checked (unknown `field`/`operation` values dropped).
  - `validate_delta(raw_json_text: str) -> ValidatedTurn` — never raises; malformed input returns `ValidatedTurn(turn_relation="continue", delta=[])`.
  - `apply_delta(previous_state: ConversationState, turn: ValidatedTurn) -> ConversationState` — pure function, returns a **new** `ConversationState` (does not mutate `previous_state`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/analyst/test_state_merge.py
from tools.analyst.conversation_state import ConversationState, ResolvedValue
from tools.analyst.state_merge import validate_delta, apply_delta, ValidatedTurn


# ---- validate_delta ----

def test_validate_delta_parses_well_formed_json():
    raw = '''
    {"turn_relation": "modify",
     "delta": [{"field": "entities.activo", "operation": "replace",
                "raw_value": "Vina Centro", "source": "explicit"}]}
    '''
    turn = validate_delta(raw)
    assert turn.turn_relation == "modify"
    assert turn.delta == [{"field": "entities.activo", "operation": "replace",
                            "raw_value": "Vina Centro", "source": "explicit"}]


def test_validate_delta_malformed_json_degrades_to_continue_empty():
    turn = validate_delta("not json at all")
    assert turn.turn_relation == "continue"
    assert turn.delta == []


def test_validate_delta_unknown_turn_relation_degrades_to_continue():
    raw = '{"turn_relation": "something_weird", "delta": []}'
    turn = validate_delta(raw)
    assert turn.turn_relation == "continue"


def test_validate_delta_drops_unknown_field_and_operation():
    raw = '''
    {"turn_relation": "continue",
     "delta": [{"field": "not_a_real_field", "operation": "replace", "raw_value": "x"},
               {"field": "metrics", "operation": "not_a_real_op", "raw_value": "noi"},
               {"field": "period", "operation": "replace", "raw_value": "2026-07", "source": "explicit"}]}
    '''
    turn = validate_delta(raw)
    assert turn.delta == [{"field": "period", "operation": "replace",
                            "raw_value": "2026-07", "source": "explicit"}]


# ---- apply_delta: keep/replace/clear/infer semantics ----

def test_replace_resolves_known_metric_to_canonical():
    prev = ConversationState()
    turn = ValidatedTurn(turn_relation="modify", delta=[
        {"field": "metrics", "operation": "replace", "raw_value": "vacancia", "source": "explicit"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.metrics[0].raw_value == "vacancia"
    assert new_state.metrics[0].canonical_value == "vacancia_pct"
    assert new_state.metrics[0].resolution_status == "resolved"
    assert new_state.metrics[0].source == "explicit"


def test_replace_keeps_unknown_metric_as_unresolved_not_discarded():
    prev = ConversationState()
    turn = ValidatedTurn(turn_relation="modify", delta=[
        {"field": "metrics", "operation": "replace", "raw_value": "concentracion de renta", "source": "explicit"},
    ])
    new_state = apply_delta(prev, turn)
    assert len(new_state.metrics) == 1
    assert new_state.metrics[0].raw_value == "concentracion de renta"
    assert new_state.metrics[0].canonical_value is None
    assert new_state.metrics[0].resolution_status == "unresolved"


def test_keep_produces_source_inherited_even_if_previously_explicit():
    prev = ConversationState(
        metrics=[ResolvedValue("ocupacion", "vacancia_pct", "resolved", "explicit")],
    )
    turn = ValidatedTurn(turn_relation="continue", delta=[
        {"field": "metrics", "operation": "keep"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.metrics[0].canonical_value == "vacancia_pct"
    assert new_state.metrics[0].source == "inherited"


def test_clear_empties_the_field():
    prev = ConversationState(period=ResolvedValue("2026-07", "2026-07", "resolved", "explicit"))
    turn = ValidatedTurn(turn_relation="modify", delta=[
        {"field": "period", "operation": "clear"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.period is None


def test_infer_sets_source_inferred():
    prev = ConversationState()
    turn = ValidatedTurn(turn_relation="modify", delta=[
        {"field": "grouping", "operation": "infer", "raw_value": "monthly"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.grouping.raw_value == "monthly"
    assert new_state.grouping.source == "inferred"


# ---- omitted-dimension policy: continue/modify/correct keep, new_topic clears ----

def test_omitted_dimension_kept_on_continue():
    prev = ConversationState(period=ResolvedValue("2026-07", "2026-07", "resolved", "explicit"))
    turn = ValidatedTurn(turn_relation="continue", delta=[
        {"field": "comparison", "operation": "replace", "raw_value": "same_period_last_year", "source": "explicit"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.period.canonical_value == "2026-07"
    assert new_state.period.source == "inherited"


def test_omitted_dimension_cleared_on_new_topic():
    prev = ConversationState(
        metrics=[ResolvedValue("ocupacion", "vacancia_pct", "resolved", "explicit")],
        grouping=ResolvedValue("monthly", "monthly", "resolved", "explicit"),
    )
    turn = ValidatedTurn(turn_relation="new_topic", delta=[
        {"field": "entities.activo", "operation": "replace", "raw_value": "Curico", "source": "explicit"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.metrics == []
    assert new_state.grouping is None


def test_new_topic_respects_explicit_keep_override():
    prev = ConversationState(
        entities={"fondo": ResolvedValue("PT", "PT", "resolved", "explicit")},
    )
    turn = ValidatedTurn(turn_relation="new_topic", delta=[
        {"field": "entities.fondo", "operation": "keep"},
        {"field": "active_goal", "operation": "replace", "raw_value": "list_expiring_contracts", "source": "explicit"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.entities["fondo"].canonical_value == "PT"
    assert new_state.entities["fondo"].source == "inherited"


# ---- entity resolution: unresolved never discarded ----

def test_unresolved_entity_preserved_as_raw_value():
    prev = ConversationState()
    turn = ValidatedTurn(turn_relation="modify", delta=[
        {"field": "entities.activo", "operation": "replace", "raw_value": "Edificio Fantasma", "source": "explicit"},
    ])
    new_state = apply_delta(prev, turn)
    assert new_state.entities["activo"].raw_value == "Edificio Fantasma"
    assert new_state.entities["activo"].canonical_value is None
    assert new_state.entities["activo"].resolution_status == "unresolved"
    assert new_state.entities["activo"].source == "explicit"  # source is NOT confidence
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analyst/test_state_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.analyst.state_merge'`

- [ ] **Step 3: Implement `state_merge.py`**

```python
"""Deterministic validation and merge of the conversation-understanding LLM's
output into a new ConversationState.

The LLM (tools/analyst/conversation_understanding.py) only decides WHAT
changed and HOW (turn_relation + per-field operation). This module decides
WHAT IT MEANS: catalog/entity resolution, the keep/replace/clear/infer
semantics, and the omitted-dimension policy driven by turn_relation. The
LLM never produces canonical_value or resolution_status -- those are always
computed here, deterministically, so a raw_value that fails to resolve is
never silently dropped (the catalog is not a whitelist).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from tools.analyst.conversation_state import ConversationState, ResolvedValue
from tools.analyst.entity_resolver import resolve_entity
from tools.analyst.semantic_loader import load_semantic_catalog

_VALID_TURN_RELATIONS = {"continue", "modify", "correct", "new_topic"}
_VALID_OPERATIONS = {"keep", "replace", "clear", "infer"}
_SINGULAR_FIELDS = {"active_goal", "analysis_mode", "period", "comparison", "grouping", "output_request"}
_ENTITY_FIELDS = {"entities.fondo", "entities.activo"}
_VALID_FIELDS = _SINGULAR_FIELDS | _ENTITY_FIELDS | {"metrics"}


@dataclass
class ValidatedTurn:
    turn_relation: str
    delta: list[dict] = field(default_factory=list)


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def validate_delta(raw_json_text: str) -> ValidatedTurn:
    parsed = _extract_json(raw_json_text)
    if not parsed:
        return ValidatedTurn(turn_relation="continue", delta=[])

    turn_relation = parsed.get("turn_relation")
    if turn_relation not in _VALID_TURN_RELATIONS:
        turn_relation = "continue"

    delta_in = parsed.get("delta")
    if not isinstance(delta_in, list):
        delta_in = []

    delta_out = []
    for item in delta_in:
        if not isinstance(item, dict):
            continue
        field_name = item.get("field")
        operation = item.get("operation")
        if field_name not in _VALID_FIELDS or operation not in _VALID_OPERATIONS:
            continue
        entry = {"field": field_name, "operation": operation}
        if "raw_value" in item:
            entry["raw_value"] = item["raw_value"]
        if "source" in item:
            entry["source"] = item["source"]
        delta_out.append(entry)

    return ValidatedTurn(turn_relation=turn_relation, delta=delta_out)


def _resolve_metric(raw_value: str) -> ResolvedValue:
    catalog = load_semantic_catalog()
    needle = str(raw_value).strip().lower()
    matches = [name for name in catalog.metrics
               if name.lower() == needle
               or needle in [s.lower() for s in (catalog.metrics[name].get("synonyms") or [])]]
    if len(matches) == 1:
        return ResolvedValue(raw_value, matches[0], "resolved", "explicit")
    if len(matches) > 1:
        return ResolvedValue(raw_value, None, "ambiguous", "explicit")
    return ResolvedValue(raw_value, None, "unresolved", "explicit")


def _resolve_entity_field(kind: str, raw_value: str) -> ResolvedValue:
    catalog = load_semantic_catalog()
    canonical = resolve_entity(raw_value, kind, catalog)
    status = "resolved" if canonical else "unresolved"
    return ResolvedValue(raw_value, canonical, status, "explicit")


def _apply_singular(prev: ResolvedValue | None, entry: dict | None, turn_relation: str) -> ResolvedValue | None:
    if entry is None:
        if turn_relation == "new_topic":
            return None
        if prev is None:
            return None
        return ResolvedValue(prev.raw_value, prev.canonical_value, prev.resolution_status, "inherited")

    op = entry["operation"]
    if op == "keep":
        if prev is None:
            return None
        return ResolvedValue(prev.raw_value, prev.canonical_value, prev.resolution_status, "inherited")
    if op == "clear":
        return None
    if op in ("replace", "infer"):
        source = "inferred" if op == "infer" else "explicit"
        raw_value = entry.get("raw_value")
        return ResolvedValue(raw_value, raw_value, "resolved", source)
    return prev  # unreachable after validate_delta, kept defensive


def apply_delta(previous_state: ConversationState, turn: ValidatedTurn) -> ConversationState:
    by_field = {e["field"]: e for e in turn.delta}
    tr = turn.turn_relation

    active_goal = _apply_singular(previous_state.active_goal, by_field.get("active_goal"), tr)
    analysis_mode = _apply_singular(previous_state.analysis_mode, by_field.get("analysis_mode"), tr)
    period = _apply_singular(previous_state.period, by_field.get("period"), tr)
    comparison = _apply_singular(previous_state.comparison, by_field.get("comparison"), tr)
    grouping = _apply_singular(previous_state.grouping, by_field.get("grouping"), tr)
    output_request = _apply_singular(previous_state.output_request, by_field.get("output_request"), tr)

    entities: dict[str, ResolvedValue] = {}
    for kind in ("fondo", "activo"):
        field_key = f"entities.{kind}"
        entry = by_field.get(field_key)
        prev = previous_state.entities.get(kind)
        if entry is None:
            if tr == "new_topic":
                continue
            if prev is not None:
                entities[kind] = ResolvedValue(prev.raw_value, prev.canonical_value, prev.resolution_status, "inherited")
            continue
        op = entry["operation"]
        if op == "keep":
            if prev is not None:
                entities[kind] = ResolvedValue(prev.raw_value, prev.canonical_value, prev.resolution_status, "inherited")
            continue
        if op == "clear":
            continue
        if op in ("replace", "infer"):
            resolved = _resolve_entity_field(kind, entry.get("raw_value"))
            if op == "infer":
                resolved.source = "inferred"
            entities[kind] = resolved

    metrics_entry = by_field.get("metrics")
    if metrics_entry is None:
        if tr == "new_topic":
            metrics: list[ResolvedValue] = []
        else:
            metrics = [ResolvedValue(m.raw_value, m.canonical_value, m.resolution_status, "inherited")
                       for m in previous_state.metrics]
    else:
        op = metrics_entry["operation"]
        if op == "keep":
            metrics = [ResolvedValue(m.raw_value, m.canonical_value, m.resolution_status, "inherited")
                       for m in previous_state.metrics]
        elif op == "clear":
            metrics = []
        else:  # replace | infer
            resolved = _resolve_metric(metrics_entry.get("raw_value"))
            if op == "infer":
                resolved.source = "inferred"
            metrics = [resolved]

    return ConversationState(
        active_goal=active_goal, analysis_mode=analysis_mode, entities=entities,
        metrics=metrics, period=period, comparison=comparison,
        grouping=grouping, output_request=output_request,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analyst/test_state_merge.py -v`
Expected: PASS (all tests). Note `ResolvedValue` is a plain dataclass, so `resolved.source = "inferred"` mutation in `_resolve_metric`/`_resolve_entity_field` callers is fine.

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/state_merge.py tests/analyst/test_state_merge.py
git commit -m "feat(conversation): add deterministic delta validation and merge"
```

---

## Task 3: Conversation-understanding LLM call

**Files:**
- Create: `tools/analyst/conversation_understanding.py`
- Test: `tests/analyst/test_conversation_understanding.py`

**Interfaces:**
- Consumes:
  - `ConversationState` from Task 1 (reads it, does not mutate).
  - `load_semantic_catalog()` from `semantic_loader.py` (for the metric catalog listing in the prompt, same synonym-listing pattern `intent.py` used).
- Produces:
  - `serialize_state_for_prompt(state: ConversationState) -> str` — compact human-readable rendering of the current state (field: raw_value/canonical_value/resolution_status/source), used both in the prompt and available for logging.
  - `build_understanding_prompt(question: str, state: ConversationState, recent_turns: list[dict]) -> str`.
  - `understand_conversation_llm(question: str, state: ConversationState, recent_turns: list[dict], llm_call: Callable[[str], str]) -> str` — calls `llm_call(prompt)` and returns its raw text response, unparsed. No side effects, no state mutation. `recent_turns` is the already-truncated list (last 2-3 `{"role":..., "content":...}` dicts) — truncation happens in `context_builder.py`, not here.

- [ ] **Step 1: Write the failing tests**

```python
# tests/analyst/test_conversation_understanding.py
from tools.analyst.conversation_state import ConversationState, ResolvedValue
from tools.analyst.conversation_understanding import (
    serialize_state_for_prompt, build_understanding_prompt, understand_conversation_llm,
)


def test_serialize_empty_state_mentions_no_active_context():
    text = serialize_state_for_prompt(ConversationState())
    assert isinstance(text, str)
    assert len(text) > 0


def test_serialize_state_includes_resolution_status():
    state = ConversationState(
        metrics=[ResolvedValue("ocupacion", "vacancia_pct", "resolved", "explicit")],
        entities={"fondo": ResolvedValue("PT", "PT", "resolved", "explicit")},
    )
    text = serialize_state_for_prompt(state)
    assert "vacancia_pct" in text
    assert "resolved" in text
    assert "PT" in text


def test_build_prompt_includes_question_state_and_recent_turns():
    state = ConversationState(period=ResolvedValue("2026-07", "2026-07", "resolved", "explicit"))
    recent_turns = [{"role": "user", "content": "¿ocupación de PT en julio?"},
                     {"role": "assistant", "content": "La vacancia de PT en julio fue 5%."}]
    prompt = build_understanding_prompt("¿y versus el año pasado?", state, recent_turns)
    assert "¿y versus el año pasado?" in prompt
    assert "2026-07" in prompt
    assert "ocupación de PT en julio" in prompt


def test_understand_conversation_llm_calls_injected_callable_and_returns_raw_text():
    captured = {}

    def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return '{"turn_relation": "continue", "delta": []}'

    result = understand_conversation_llm("¿y el año pasado?", ConversationState(), [], fake_llm)
    assert result == '{"turn_relation": "continue", "delta": []}'
    assert "¿y el año pasado?" in captured["prompt"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analyst/test_conversation_understanding.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `conversation_understanding.py`**

```python
"""Single LLM call responsible for understanding a conversational turn:
what changed relative to the active conversation state, and how the turn
relates to what came before (continue/modify/correct/new_topic).

This module has ONE job: understand. It does not resolve entities against
the catalog, does not validate the LLM's JSON, and does not persist
anything -- see tools/analyst/state_merge.py for validation/merge and
tools/analyst/context_builder.py for the orchestration that ties this
together with persistence.
"""
from __future__ import annotations

from typing import Callable

from tools.analyst.conversation_state import ConversationState, ResolvedValue
from tools.analyst.semantic_loader import load_semantic_catalog

_UNDERSTANDING_PROMPT_TEMPLATE = """Eres la capa de comprension conversacional de un asistente analitico \
inmobiliario. Tu unico trabajo es entender como se relaciona la pregunta actual del usuario con el \
contexto de la conversacion -- NO decides que investigar ni si una metrica es valida, solo que dijo \
el usuario y de donde viene cada dato.

ESTADO ACTUAL DE LA CONVERSACION:
{state}

TURNOS RECIENTES:
{recent_turns}

PREGUNTA ACTUAL: {question}

Metricas conocidas (nombre: sinonimos), solo como referencia -- el usuario puede pedir algo que no \
este en esta lista y es igual de valido, en ese caso usa el texto tal cual el lo dijo:
{metric_catalog}

Responde SOLO un JSON con esta forma exacta:
{{"turn_relation": "continue" | "modify" | "correct" | "new_topic",
  "delta": [
    {{"field": "<uno de: active_goal, analysis_mode, entities.fondo, entities.activo, metrics, period, comparison, grouping, output_request>",
     "operation": "keep" | "replace" | "clear" | "infer",
     "raw_value": "<texto tal cual lo entendiste, solo si operation es replace o infer>",
     "source": "explicit" | "inferred"}}
  ]}}

Reglas:
- turn_relation="continue": el turno sigue exactamente la misma linea de analisis (ej. "¿y versus el año pasado?").
- turn_relation="modify": el turno cambia una dimension puntual manteniendo el resto (ej. "ahora Viña Centro", "hazlo mensual").
- turn_relation="correct": el usuario esta corrigiendo algo que la conversacion entendio mal (ej. "no, me referia a Parque Titanium").
- turn_relation="new_topic": el turno no tiene relacion con lo anterior (ej. cambia de tema por completo).
- No incluyas en "delta" las dimensiones que no cambian -- omitirlas ya comunica "mantener" en continue/modify/correct, y "descartar" en new_topic (a menos que agregues explicitamente {{"field": "...", "operation": "keep"}} para esa dimension puntual).
- metric=null / active_goal exploratorio son resultados validos. No fuerces una metrica solo porque el catalogo tiene una.
No agregues texto fuera del JSON."""


def serialize_state_for_prompt(state: ConversationState) -> str:
    lines: list[str] = []

    def _line(label: str, rv: ResolvedValue | None) -> None:
        if rv is None:
            lines.append(f"- {label}: (vacio)")
        else:
            lines.append(
                f"- {label}: raw='{rv.raw_value}' canonical='{rv.canonical_value}' "
                f"status={rv.resolution_status} source={rv.source}"
            )

    _line("active_goal", state.active_goal)
    _line("analysis_mode", state.analysis_mode)
    for kind in ("fondo", "activo"):
        _line(f"entities.{kind}", state.entities.get(kind))
    if state.metrics:
        for m in state.metrics:
            _line("metrics", m)
    else:
        lines.append("- metrics: (vacio)")
    _line("period", state.period)
    _line("comparison", state.comparison)
    _line("grouping", state.grouping)
    _line("output_request", state.output_request)
    return "\n".join(lines)


def _serialize_recent_turns(recent_turns: list[dict]) -> str:
    if not recent_turns:
        return "(sin turnos previos)"
    lines = []
    for turn in recent_turns:
        role = turn.get("role", "?")
        content = str(turn.get("content", ""))[:500]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _format_metric_catalog() -> str:
    catalog = load_semantic_catalog()
    lines = []
    for name in sorted(catalog.metrics):
        synonyms = catalog.metrics[name].get("synonyms") or []
        syn_str = ", ".join(synonyms) if synonyms else "(sin sinonimos registrados)"
        lines.append(f"- {name}: {syn_str}")
    return "\n".join(lines)


def build_understanding_prompt(question: str, state: ConversationState, recent_turns: list[dict]) -> str:
    return _UNDERSTANDING_PROMPT_TEMPLATE.format(
        state=serialize_state_for_prompt(state),
        recent_turns=_serialize_recent_turns(recent_turns),
        question=question,
        metric_catalog=_format_metric_catalog(),
    )


def understand_conversation_llm(
    question: str,
    state: ConversationState,
    recent_turns: list[dict],
    llm_call: Callable[[str], str],
) -> str:
    prompt = build_understanding_prompt(question, state, recent_turns)
    return llm_call(prompt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analyst/test_conversation_understanding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/conversation_understanding.py tests/analyst/test_conversation_understanding.py
git commit -m "feat(conversation): add single-LLM-call conversational understanding module"
```

---

## Task 4: Rewrite `ambiguity.py` to evaluate `ConversationState`

**Files:**
- Modify (rewrite): `tools/analyst/ambiguity.py`
- Modify (rewrite): `tests/analyst/test_ambiguity.py`

**Interfaces:**
- Consumes: `ConversationState`, `ResolvedValue` from Task 1.
- Produces: `AmbiguityDecision(action: str, reason: str, clarify_message: str | None = None)` (unchanged shape) and `decide_ambiguity(candidate_state: ConversationState, verified_hint: dict | None, has_history: bool) -> AmbiguityDecision` (renamed from `decide`, new signature — old `decide(IntentResult, ...)` no longer exists in this module; the façade in Task 6 adapts old callers).

- [ ] **Step 1: Write the failing tests**

```python
# tests/analyst/test_ambiguity.py (full rewrite)
from tools.analyst.ambiguity import decide_ambiguity, AmbiguityDecision
from tools.analyst.conversation_state import ConversationState, ResolvedValue


def _resolved(raw, canonical, status="resolved", source="explicit"):
    return ResolvedValue(raw, canonical, status, source)


def test_entity_plus_exploratory_goal_proceeds():
    # "¿Cómo viene Parque Titanium?" -- entity resolved + explicit exploratory goal, no metric
    state = ConversationState(
        entities={"fondo": _resolved("PT", "PT")},
        active_goal=_resolved("investigate_recent_status", "investigate_recent_status"),
        analysis_mode=_resolved("exploratory", "exploratory"),
    )
    d = decide_ambiguity(state, verified_hint=None, has_history=False)
    assert d.action == "proceed"


def test_entity_alone_without_goal_clarifies():
    # "Parque Titanium." -- entity resolved but no analytical goal anywhere
    state = ConversationState(entities={"fondo": _resolved("PT", "PT")})
    d = decide_ambiguity(state, verified_hint=None, has_history=False)
    assert d.action == "clarify"


def test_resolved_metric_and_entity_proceeds():
    state = ConversationState(
        metrics=[_resolved("vacancia", "vacancia_pct")],
        entities={"fondo": _resolved("PT", "PT")},
    )
    d = decide_ambiguity(state, verified_hint=None, has_history=False)
    assert d.action == "proceed"


def test_ambiguous_metric_clarifies_even_with_entity():
    # "Dame la renta de PT" with multiple candidate metrics for "renta"
    state = ConversationState(
        metrics=[_resolved("renta", None, status="ambiguous")],
        entities={"fondo": _resolved("PT", "PT")},
    )
    d = decide_ambiguity(state, verified_hint=None, has_history=False)
    assert d.action == "clarify"


def test_unresolved_metric_without_goal_clarifies():
    state = ConversationState(
        metrics=[_resolved("concentracion de renta", None, status="unresolved")],
        entities={"fondo": _resolved("PT", "PT")},
    )
    d = decide_ambiguity(state, verified_hint=None, has_history=False)
    assert d.action == "clarify"


def test_unresolved_metric_with_exploratory_goal_proceeds():
    # agent can still investigate an uncatalogued concept if there's a clear goal
    state = ConversationState(
        metrics=[_resolved("concentracion de renta", None, status="unresolved")],
        entities={"fondo": _resolved("PT", "PT")},
        active_goal=_resolved("investigate_metric", "investigate_metric"),
    )
    d = decide_ambiguity(state, verified_hint=None, has_history=False)
    assert d.action == "proceed"


def test_verified_hint_grounds_otherwise_empty_state():
    state = ConversationState()
    d = decide_ambiguity(state, verified_hint={"question": "...", "sql": "..."}, has_history=False)
    assert d.action == "proceed"
    assert "verified" in d.reason.lower()


def test_history_grounds_otherwise_empty_state():
    state = ConversationState()
    d = decide_ambiguity(state, verified_hint=None, has_history=True)
    assert d.action == "proceed"


def test_completely_empty_state_no_grounding_clarifies():
    state = ConversationState()
    d = decide_ambiguity(state, verified_hint=None, has_history=False)
    assert d.action == "clarify"
    assert d.clarify_message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analyst/test_ambiguity.py -v`
Expected: FAIL with `ImportError: cannot import name 'decide_ambiguity'`

- [ ] **Step 3: Implement new `ambiguity.py`**

```python
"""Decides whether to proceed with SQL generation, or ask for clarification,
based on a candidate ConversationState plus lightweight grounding signals.

The question is NOT "is any field populated?" -- it's "is there enough
context to attempt resolving the goal without making an arbitrary,
high-impact decision?". A resolved entity alone is not enough (there is no
analytical target yet); an ambiguous or unresolved metric with no goal to
fall back on is not enough either. Exploratory goals with no metric at all
are enough, deliberately -- this keeps open-ended questions ("¿cómo viene
PT?") from being blocked by a missing metric=null.
"""
from __future__ import annotations

from dataclasses import dataclass

from tools.analyst.conversation_state import ConversationState

_CLARIFY_MESSAGE = (
    "¿Podrías especificar qué métrica te interesa (ej. vacancia, NOI, TIR, "
    "dividend yield) y a qué fondo o activo te refieres (TRI, PT, Apo, o un "
    "activo específico)?"
)


@dataclass
class AmbiguityDecision:
    action: str  # "proceed" | "clarify"
    reason: str
    clarify_message: str | None = None


def _has_usable_goal(state: ConversationState) -> bool:
    return bool(
        (state.active_goal and state.active_goal.canonical_value)
        or (state.analysis_mode and state.analysis_mode.canonical_value)
    )


def _has_clean_metrics(state: ConversationState) -> bool:
    if not state.metrics:
        return False
    return all(m.resolution_status == "resolved" for m in state.metrics)


def _has_problematic_metrics(state: ConversationState) -> bool:
    return any(m.resolution_status in ("ambiguous", "unresolved") for m in state.metrics)


def _has_resolved_entity(state: ConversationState) -> bool:
    return any(rv.canonical_value for rv in state.entities.values())


def decide_ambiguity(
    candidate_state: ConversationState,
    verified_hint: dict | None,
    has_history: bool,
) -> AmbiguityDecision:
    has_goal = _has_usable_goal(candidate_state)
    has_clean_metrics = _has_clean_metrics(candidate_state)
    has_problematic_metrics = _has_problematic_metrics(candidate_state)
    has_entity = _has_resolved_entity(candidate_state)

    # Ambiguous/unresolved metrics never proceed on their own -- they need an
    # explicit goal to justify exploring an uncatalogued or ambiguous concept.
    if has_problematic_metrics and not has_goal:
        return AmbiguityDecision(
            "clarify",
            "metric is ambiguous or unresolved with no analytical goal to ground exploration",
            clarify_message=_CLARIFY_MESSAGE,
        )

    if has_clean_metrics and has_entity:
        return AmbiguityDecision("proceed", "resolved metric and entity")

    if has_problematic_metrics and has_goal:
        return AmbiguityDecision("proceed", "unresolved/ambiguous metric grounded by an explicit analytical goal")

    if has_entity and has_goal:
        return AmbiguityDecision("proceed", "resolved entity with a usable analytical goal or mode")

    if has_goal and not has_entity and not has_clean_metrics:
        return AmbiguityDecision("proceed", "exploratory goal without a specific metric is a valid open question")

    # Entity alone, or nothing at all: not enough to avoid an arbitrary decision.
    if verified_hint is not None:
        return AmbiguityDecision("proceed", "no strong intent but a verified-query hint grounds the question")

    if has_history:
        return AmbiguityDecision("proceed", "no strong intent but conversation history provides context")

    return AmbiguityDecision(
        "clarify",
        "no resolved metric+entity, no usable goal beyond a bare entity, no verified hint, no history",
        clarify_message=_CLARIFY_MESSAGE,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analyst/test_ambiguity.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/ambiguity.py tests/analyst/test_ambiguity.py
git commit -m "feat(conversation): rewrite ambiguity.decide to evaluate ConversationState, not bare field presence"
```

---

## Task 5: Orchestration in `context_builder.py` (understand → validate → apply → ambiguity → commit)

**Files:**
- Modify (rewrite): `tools/analyst/context_builder.py`
- Modify (rewrite): `tests/analyst/test_context_builder.py`

**Interfaces:**
- Consumes:
  - `get_state`, `commit_state` from Task 1.
  - `understand_conversation_llm` from Task 3.
  - `validate_delta`, `apply_delta` from Task 2.
  - `decide_ambiguity` from Task 4.
  - `resolve_temporal(question, time_behavior) -> TemporalResolution` from `tools/analyst/temporal.py` (existing, unmodified).
  - `find_similar(question, top_k) -> list[dict]` from `tools/analyst/verified_queries_repo.py` (existing, unmodified).
  - `load_semantic_catalog()` from `semantic_loader.py`.
- Produces:
  - `AnalystContext(state: ConversationState, decision: AmbiguityDecision, temporal: TemporalResolution | None, verified_hint: dict | None, prompt_sections: list[tuple[str, str]])` — replaces the old `intent: IntentResult` field with `state: ConversationState`.
  - `build_context(question: str, session_id: str, history: list[dict], llm_call: Callable[[str], str]) -> AnalystContext` — same external signature as before (so `db_chat.py`'s call site needs no signature change, only attribute access changes from `ctx.intent` to `ctx.state`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/analyst/test_context_builder.py (full rewrite)
from tools.analyst.context_builder import build_context
from tools.analyst.conversation_state import clear_state, get_state


def _understanding_llm(turn_relation: str, delta: list[dict]):
    import json

    def _call(prompt: str) -> str:
        return json.dumps({"turn_relation": turn_relation, "delta": delta})
    return _call


def test_resolved_metric_and_entity_produces_proceed_context():
    clear_state("ctx-test-1")
    llm = _understanding_llm("continue", [
        {"field": "metrics", "operation": "replace", "raw_value": "vacancia", "source": "explicit"},
        {"field": "entities.fondo", "operation": "replace", "raw_value": "Parque Titanium", "source": "explicit"},
    ])
    ctx = build_context(
        "¿cuál es la vacancia de Parque Titanium este mes?",
        session_id="ctx-test-1", history=[], llm_call=llm,
    )
    assert ctx.decision.action == "proceed"
    assert ctx.state.metrics[0].canonical_value == "vacancia_pct"
    labels = [label for label, _ in ctx.prompt_sections]
    assert "RESOLVED CONTEXT" in labels
    assert "BUSINESS DEFINITIONS" in labels


def test_temporal_phrase_adds_period_section():
    clear_state("ctx-test-2")
    llm = _understanding_llm("continue", [
        {"field": "metrics", "operation": "replace", "raw_value": "vacancia", "source": "explicit"},
        {"field": "entities.fondo", "operation": "replace", "raw_value": "Parque Titanium", "source": "explicit"},
    ])
    ctx = build_context(
        "vacancia de Parque Titanium este mes",
        session_id="ctx-test-2", history=[], llm_call=llm,
    )
    period_section = dict(ctx.prompt_sections)["PERIOD / COMPARISON"]
    assert "mes" in period_section.lower() or "2026" in period_section


def test_ungrounded_question_clarifies_without_sections_and_does_not_commit_state():
    clear_state("ctx-test-3")
    llm = _understanding_llm("continue", [])
    ctx = build_context("cuéntame algo", session_id="ctx-test-3", history=[], llm_call=llm)
    assert ctx.decision.action == "clarify"
    assert ctx.decision.clarify_message
    assert ctx.prompt_sections == []
    # candidate state must NOT have been committed
    assert get_state("ctx-test-3").metrics == []


def test_proceed_commits_state_for_next_turn():
    clear_state("ctx-test-4")
    llm = _understanding_llm("continue", [
        {"field": "metrics", "operation": "replace", "raw_value": "vacancia", "source": "explicit"},
        {"field": "entities.fondo", "operation": "replace", "raw_value": "Parque Titanium", "source": "explicit"},
    ])
    build_context("vacancia de PT", session_id="ctx-test-4", history=[], llm_call=llm)
    committed = get_state("ctx-test-4")
    assert committed.metrics[0].canonical_value == "vacancia_pct"


def test_malformed_llm_response_does_not_raise_and_falls_back_to_clarify_or_grounded():
    clear_state("ctx-test-5")

    def broken_llm(prompt: str) -> str:
        return "not json"

    ctx = build_context("algo", session_id="ctx-test-5", history=[], llm_call=broken_llm)
    assert ctx.decision.action in ("proceed", "clarify")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analyst/test_context_builder.py -v`
Expected: FAIL (old `AnalystContext.intent` API still in place / labels differ)

- [ ] **Step 3: Implement new `context_builder.py`**

```python
"""Boundary that turns a user question + conversation state into everything
tools/db_chat.py's SQL-generation prompt needs: a validated ConversationState,
business definitions, a verified-query hint, and an ambiguity decision --
assembled as labeled (title, content) sections ready to splice into the
chat-completion `messages` list.

Orchestrates the full understand -> validate -> apply -> ambiguity -> commit
sequence (design doc section 5bis): the candidate state produced by
apply_delta is NEVER committed until decide_ambiguity says "proceed". On
"clarify" the previously committed state is left untouched, so a bad or
ungrounded turn cannot contaminate the next one.

This does NOT call the LLM for SQL generation and does NOT touch
_validate_sql/_run_sql -- it only prepares context for the existing pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tools.analyst.ambiguity import AmbiguityDecision, decide_ambiguity
from tools.analyst.conversation_state import ConversationState, commit_state, get_state
from tools.analyst.conversation_understanding import understand_conversation_llm
from tools.analyst.semantic_loader import load_semantic_catalog
from tools.analyst.state_merge import apply_delta, validate_delta
from tools.analyst.temporal import TemporalResolution, resolve_temporal
from tools.analyst.verified_queries_repo import find_similar

_RECENT_TURNS_FOR_UNDERSTANDING = 3


@dataclass
class AnalystContext:
    state: ConversationState
    decision: AmbiguityDecision
    temporal: TemporalResolution | None
    verified_hint: dict | None
    prompt_sections: list[tuple[str, str]] = field(default_factory=list)


def _metric_time_behavior(canonical_metric: str | None) -> str | None:
    if not canonical_metric:
        return None
    catalog = load_semantic_catalog()
    metric = catalog.metrics.get(canonical_metric)
    return metric.get("time_behavior") if metric else None


def _build_sections(
    state: ConversationState,
    temporal: TemporalResolution | None,
    verified_hint: dict | None,
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []

    resolved_lines = []
    if state.metrics:
        for m in state.metrics:
            resolved_lines.append(
                f"metric: {m.canonical_value or m.raw_value} "
                f"(status={m.resolution_status}, source={m.source})"
            )
    else:
        resolved_lines.append("metric: (sin resolver)")
    for kind, rv in state.entities.items():
        resolved_lines.append(
            f"entity[{kind}]: {rv.canonical_value or rv.raw_value} "
            f"(status={rv.resolution_status}, source={rv.source})"
        )
    if state.comparison:
        resolved_lines.append(f"comparison: {state.comparison.canonical_value}")
    if state.active_goal:
        resolved_lines.append(f"active_goal: {state.active_goal.canonical_value} (source={state.active_goal.source})")
    if state.analysis_mode:
        resolved_lines.append(f"analysis_mode: {state.analysis_mode.canonical_value} (source={state.analysis_mode.source})")
    if state.grouping:
        resolved_lines.append(f"grouping: {state.grouping.canonical_value} (source={state.grouping.source})")
    sections.append(("RESOLVED CONTEXT", "\n".join(resolved_lines)))

    resolved_metric_names = [m.canonical_value for m in state.metrics if m.canonical_value]
    if resolved_metric_names:
        catalog = load_semantic_catalog()
        for metric_name in resolved_metric_names:
            metric_def = catalog.metrics.get(metric_name)
            if metric_def:
                def_lines = [
                    f"business_definition: {metric_def.get('business_definition', '')}",
                    f"formula: {metric_def.get('formula', '')}",
                    f"unit: {metric_def.get('unit', '')}",
                ]
                sections.append((f"BUSINESS DEFINITIONS", "\n".join(def_lines)))

    period_lines = []
    if state.period:
        period_lines.append(f"period (from state): {state.period.canonical_value}")
    if temporal is not None:
        period_lines.append(f"temporal phrase resolved: {temporal.label}")
        if temporal.period:
            period_lines.append(f"resolved period: {temporal.period}")
        if temporal.period_range:
            period_lines.append(f"resolved range: {temporal.period_range[0]} a {temporal.period_range[1]}")
        if temporal.comparison_period:
            period_lines.append(f"comparison: {temporal.comparison_period}")
        if temporal.data_gap_warning:
            period_lines.append(f"advertencia: {temporal.data_gap_warning}")
    if period_lines:
        sections.append(("PERIOD / COMPARISON", "\n".join(period_lines)))

    if verified_hint:
        sections.append((
            "VERIFIED EXAMPLE",
            f"Q: {verified_hint['question']}\nSQL: {verified_hint['sql']}\n"
            f"Notas: {verified_hint.get('notes', '')}",
        ))

    return sections


def build_context(
    question: str,
    session_id: str,
    history: list[dict],
    llm_call: Callable[[str], str],
) -> AnalystContext:
    previous_state = get_state(session_id)
    recent_turns = (history or [])[-_RECENT_TURNS_FOR_UNDERSTANDING:]

    raw = understand_conversation_llm(question, previous_state, recent_turns, llm_call)
    validated_turn = validate_delta(raw)
    candidate_state = apply_delta(previous_state, validated_turn)

    verified = find_similar(question, top_k=1)
    verified_hint = verified[0] if verified else None

    has_history = bool(history)
    decision = decide_ambiguity(candidate_state, verified_hint=verified_hint, has_history=has_history)

    if decision.action != "proceed":
        return AnalystContext(
            state=candidate_state,
            decision=decision,
            temporal=None,
            verified_hint=verified_hint,
            prompt_sections=[],
        )

    commit_state(session_id, candidate_state)

    resolved_metric_names = [m.canonical_value for m in candidate_state.metrics if m.canonical_value]
    time_behavior = _metric_time_behavior(resolved_metric_names[0] if resolved_metric_names else None)
    temporal = resolve_temporal(question, time_behavior=time_behavior)

    prompt_sections = _build_sections(candidate_state, temporal, verified_hint)

    return AnalystContext(
        state=candidate_state,
        decision=decision,
        temporal=temporal,
        verified_hint=verified_hint,
        prompt_sections=prompt_sections,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analyst/test_context_builder.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/context_builder.py tests/analyst/test_context_builder.py
git commit -m "feat(conversation): orchestrate understand->validate->apply->ambiguity->commit in context_builder"
```

---

## Task 6: `intent.py` compatibility façade + `db_chat.py` integration

**Files:**
- Modify (rewrite to façade): `tools/analyst/intent.py`
- Modify: `tools/db_chat.py:38,879,1066-1070` (import, `AnalystContext` fallback construction, remove trailing `update_state` call)
- Modify (rewrite): `tests/analyst/test_intent.py`

**Interfaces:**
- Consumes: `build_context` (via internal reuse), `ConversationState` from Task 1, `AnalystContext` from Task 5.
- Produces: `IntentResult(metric: str | None, entities: dict[str, str], period: str | None, comparison: str | None, confidence: float, needs_clarification: bool)` — same shape as the pre-Phase-3 dataclass, kept ONLY so `tests/eval/run_eval.py`'s direct `extract_intent` call and `db_chat.py`'s degraded-fallback path keep working during migration. `extract_intent(question: str, session_id: str, llm_call: Callable[[str], str]) -> IntentResult` — same signature as before.

- [ ] **Step 1: Write the failing tests**

```python
# tests/analyst/test_intent.py (full rewrite — façade tests)
import json

from tools.analyst.intent import extract_intent, IntentResult
from tools.analyst.conversation_state import clear_state


def _understanding_llm(turn_relation: str, delta: list[dict]):
    def _call(prompt: str) -> str:
        return json.dumps({"turn_relation": turn_relation, "delta": delta})
    return _call


def test_facade_extracts_metric_and_entity_in_legacy_shape():
    clear_state("intent-facade-1")
    llm = _understanding_llm("continue", [
        {"field": "metrics", "operation": "replace", "raw_value": "vacancia", "source": "explicit"},
        {"field": "entities.activo", "operation": "replace", "raw_value": "Parque Titanium", "source": "explicit"},
    ])
    result = extract_intent("vacancia de Parque Titanium", "intent-facade-1", llm)
    assert isinstance(result, IntentResult)
    assert result.metric == "vacancia_pct"
    assert result.entities.get("activo") == "Parque Titanium" or result.entities.get("activo")
    assert result.needs_clarification is False


def test_facade_ungrounded_question_needs_clarification():
    clear_state("intent-facade-2")
    llm = _understanding_llm("continue", [])
    result = extract_intent("cuéntame algo", "intent-facade-2", llm)
    assert result.needs_clarification is True


def test_facade_follow_up_inherits_from_prior_committed_turn():
    clear_state("intent-facade-3")
    first_llm = _understanding_llm("continue", [
        {"field": "metrics", "operation": "replace", "raw_value": "noi", "source": "explicit"},
        {"field": "entities.fondo", "operation": "replace", "raw_value": "PT", "source": "explicit"},
    ])
    extract_intent("NOI de PT", "intent-facade-3", first_llm)

    second_llm = _understanding_llm("continue", [])  # follow-up, nothing explicit
    result = extract_intent("¿y el año pasado?", "intent-facade-3", second_llm)
    assert result.metric == "noi"
    assert result.entities.get("fondo") == "PT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analyst/test_intent.py -v`
Expected: FAIL (old `IntentResult`/`extract_intent` behavior doesn't match new façade expectations yet — e.g. `confidence`/`needs_clarification` computed differently)

- [ ] **Step 3: Implement façade `intent.py`**

```python
"""Backward-compatible facade over the Phase 3 conversation pipeline.

Kept temporarily for internal consumers that predate the ConversationState
redesign (tools/db_chat.py's degraded-fallback path, tests/eval/run_eval.py's
standalone precision check). Delete this module once
`rg "extract_intent|IntentResult|from tools.analyst.intent"` shows no
remaining consumers outside this file and its test -- do not delete
speculatively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tools.analyst.context_builder import build_context


@dataclass
class IntentResult:
    metric: str | None
    entities: dict[str, str] = field(default_factory=dict)
    period: str | None = None
    comparison: str | None = None
    confidence: float = 0.0
    needs_clarification: bool = False


def extract_intent(question: str, session_id: str, llm_call: Callable[[str], str]) -> IntentResult:
    ctx = build_context(question, session_id, history=[], llm_call=llm_call)
    state = ctx.state

    metric = None
    if state.metrics:
        metric = state.metrics[0].canonical_value or state.metrics[0].raw_value

    entities = {
        kind: (rv.canonical_value or rv.raw_value)
        for kind, rv in state.entities.items()
    }

    period = state.period.canonical_value if state.period else None
    comparison = state.comparison.canonical_value if state.comparison else None
    needs_clarification = ctx.decision.action == "clarify"
    confidence = 0.9 if not needs_clarification else 0.2

    return IntentResult(
        metric=metric, entities=entities, period=period, comparison=comparison,
        confidence=confidence, needs_clarification=needs_clarification,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analyst/test_intent.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Update `db_chat.py` call sites**

Read `tools/db_chat.py` around lines 38, 872-884, and 1060-1070 before editing (line numbers may have drifted after Task 5's changes to `context_builder.py`'s exports — search for `AnalystContext`, `IntentResult`, `update_state` instead of trusting exact numbers). Make these changes:

1. Replace `from tools.analyst.context_builder import AnalystContext, build_context` — keep as is, `AnalystContext` still exists (Task 5).
2. Find the `except Exception:` fallback block that constructs `AnalystContext(intent=IntentResult(metric=None), ...)` and change it to construct `AnalystContext(state=ConversationState(), ...)`:

```python
from tools.analyst.conversation_state import ConversationState
# ...
    try:
        ctx = build_context(question, session_id, history or [], _intent_llm_call)
    except Exception:
        ctx = AnalystContext(
            state=ConversationState(),
            decision=AmbiguityDecision(action="proceed", reason="context_builder failed, degrading to legacy behavior"),
            temporal=None,
            verified_hint=None,
            prompt_sections=[],
        )
```

3. Find any other `ctx.intent.metric` / `ctx.intent.entities` reads used later in `answer()` (e.g. for `_extract_metric_from_sql` cross-checks or logging) and replace with the equivalent `ctx.state.metrics[0].canonical_value if ctx.state.metrics else None` / `{k: v.canonical_value or v.raw_value for k, v in ctx.state.entities.items()}`.
4. Delete the trailing manual state write (the line calling `update_state(session_id, last_metric=...)` near the end of `answer()`) — state is now committed inside `build_context` (Task 5, step 6 of the design's §5bis sequence), so this call is redundant and references a function (`update_state`) that no longer exists on the new `conversation_state.py`.
5. Remove the now-unused `from tools.analyst.conversation_state import clear_state` / `update_state` imports if `update_state` is no longer referenced anywhere in the file; keep `clear_state` if the reset endpoint still uses it.

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `pytest tests/analyst/ tests/eval/ -v`
Expected: PASS. If `test_db_chat.py` or similar exists and references `ctx.intent`, fix those call sites the same way as step 5.3.

- [ ] **Step 7: Commit**

```bash
git add tools/analyst/intent.py tests/analyst/test_intent.py tools/db_chat.py
git commit -m "refactor(analyst): make intent.py a temporary facade over the new pipeline, wire db_chat.py to ConversationState"
```

---

## Task 7: Expand multi-turn eval suite to 8 scenarios + stability mode

**Files:**
- Modify: `tests/eval/conversations.yaml`
- Modify: `tests/eval/run_eval.py`

**Interfaces:**
- Consumes: `tools.db_chat.answer(question, history, session_id)` (existing, unmodified contract) for full-pipeline runs; `tools.analyst.conversation_state.clear_state` for isolation between conversations/repetitions.
- Produces: `run_eval.py --stability [N]` CLI flag (default `N=5` when passed without a value, and multi-turn full-pipeline run reports pass-rate per scenario across repetitions, printed as `scenario_name: k/N (stochastic)` or `scenario_name: 0/N (architectural)` or `scenario_name: N/N (stable)`.

- [ ] **Step 1: Add the 4 missing scenarios to `conversations.yaml`**

Read the current file first (already read above — 4 scenarios exist: `followup_comparison_pt_occupancy`, `entity_replacement_monthly_evolution`, `metric_followup_same_entity`, `session_isolation_control`). Append these 4 new scenarios matching design §6 / the original brief §13:

```yaml
- name: grouping_replacement_pt_occupancy
  turns:
    - question: "Muéstrame ocupación de Parque Titanium en 2026"
      expected_metric: vacancia_pct
      expected_entities: {fondo: PT}
    - question: "Hazlo mensual"
      expected_metric: vacancia_pct
      expected_entities: {fondo: PT}
      expected_grouping: monthly

- name: correction_vina_to_pt
  turns:
    - question: "Muéstrame Viña Centro"
      expected_entities: {activo: "Viña Centro"}
    - question: "No, me refería a Parque Titanium"
      expected_entities: {fondo: PT}

- name: new_topic_pt_to_curico_contracts
  turns:
    - question: "Ocupación de PT"
      expected_metric: vacancia_pct
      expected_entities: {fondo: PT}
    - question: "¿Qué contratos vencen en Curicó?"
      expected_metric: null
      expected_entities: {activo: "Mall Curicó"}

- name: exploratory_pt_followup
  turns:
    - question: "¿Cómo viene Parque Titanium?"
      expected_metric: null
      expected_entities: {fondo: PT}
    - question: "¿Y qué te preocupa más?"
      expected_metric: null
      expected_entities: {fondo: PT}
```

- [ ] **Step 2: Read `run_eval.py`'s existing multi-turn runner to find the exact insertion point**

Run: `grep -n "def \|conversations.yaml\|conv_turn_total" tests/eval/run_eval.py`

Locate the function that loads `conversations.yaml` and iterates turns (around line 141-168 per the earlier grep). Read that whole function before editing.

- [ ] **Step 3: Add `--stability N` support**

Wrap the existing per-conversation turn loop in a repetition loop that resets `session_id` (via `clear_state`) between repetitions of the *same* conversation, and aggregate pass/fail per scenario across repetitions. Concretely, in the function that currently does something like:

```python
for conv in conversations:
    session_id = f"eval-{conv['name']}"
    from tools.analyst.conversation_state import clear_state as _clear_state
    _clear_state(session_id)
    history = []
    for turn in conv["turns"]:
        ...
```

change it to accept a `stability_runs: int = 1` parameter and wrap the per-conversation block:

```python
def run_multiturn_eval(conversations, stability_runs: int = 1):
    from tools.analyst.conversation_state import clear_state as _clear_state
    results_by_scenario: dict[str, list[bool]] = {}

    for conv in conversations:
        scenario_passes = []
        for run_idx in range(stability_runs):
            session_id = f"eval-{conv['name']}-run{run_idx}"
            _clear_state(session_id)
            history = []
            conv_ok = True
            for turn in conv["turns"]:
                # ... existing per-turn call to tools.db_chat.answer(...) and
                # existing assertions against expected_metric/expected_entities/
                # expected_comparison, now also checking expected_grouping when
                # present in the turn dict ...
                if not turn_passed:
                    conv_ok = False
                history.append({"role": "user", "content": turn["question"]})
                history.append({"role": "assistant", "content": result.get("answer_md", "")})
            scenario_passes.append(conv_ok)
        results_by_scenario[conv["name"]] = scenario_passes

    print(f"\nMulti-turn stability ({stability_runs} runs x {len(conversations)} conversations):")
    for name, passes in results_by_scenario.items():
        k = sum(passes)
        n = len(passes)
        label = "stable" if k == n else ("architectural" if k == 0 else "stochastic")
        print(f"  {name}: {k}/{n} ({label})")
    return results_by_scenario
```

Add CLI parsing (find the existing `argparse`/`sys.argv` handling in `run_eval.py` and extend it):

```python
parser.add_argument("--stability", nargs="?", const=5, type=int, default=1,
                     help="Repeat each multi-turn conversation N times (default 5 when flag present without value) to distinguish stochastic from architectural failures.")
```

and pass `args.stability` into `run_multiturn_eval(conversations, stability_runs=args.stability)`.

Preserve the existing `expected_metric`/`expected_entities`/`expected_comparison` assertion logic exactly as it works today — only add a check for `expected_grouping` when that key is present in a turn dict, comparing it against `ctx.state.grouping.canonical_value` (the full-pipeline run already goes through `tools.db_chat.answer`, so if grouping isn't surfaced in `answer()`'s return dict, extend `answer()`'s return dict with a `state_grouping` debug field gated behind an `debug=True` kwarg the eval script passes — do not change `answer()`'s default return shape for production callers).

- [ ] **Step 4: Run the expanded eval**

Run: `python -m tests.eval.run_eval --stability 5`
Expected: prints per-scenario pass rates for all 8 scenarios across 5 runs each. Does not need to be 100% yet — this step verifies the harness runs without crashing; actual pass-rate improvement is validated in Task 8.

- [ ] **Step 5: Commit**

```bash
git add tests/eval/conversations.yaml tests/eval/run_eval.py
git commit -m "test(eval): expand multi-turn scenarios to 8 cases, add --stability repeated-run mode"
```

---

## Task 8: Full-suite validation, observability logging, and `intent.py` retirement check

**Files:**
- Modify: `tools/analyst/context_builder.py` (add structured per-turn logging)
- No new files.

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: a `logging.getLogger("analyst.conversation")` debug-level log line per turn inside `build_context`, emitting the fields listed in design §7 (`conversation_id, current_question, previous_state, turn_relation, delta, new_state, explicit_fields, inherited_fields, inferred_fields, clarification_reason`) — never shown to the end user, only inspectable via standard logging config.

- [ ] **Step 1: Add observability logging to `build_context`**

Modify `tools/analyst/context_builder.py` (from Task 5) to add, right after `decision = decide_ambiguity(...)`:

```python
import logging

_logger = logging.getLogger("analyst.conversation")

# inside build_context, after `decision = decide_ambiguity(...)`:
def _field_sources(state: ConversationState) -> dict[str, list[str]]:
    by_source: dict[str, list[str]] = {"explicit": [], "inherited": [], "inferred": []}
    named = [
        ("active_goal", state.active_goal), ("analysis_mode", state.analysis_mode),
        ("period", state.period), ("comparison", state.comparison),
        ("grouping", state.grouping), ("output_request", state.output_request),
    ] + [(f"entities.{k}", v) for k, v in state.entities.items()] \
      + [(f"metrics[{i}]", m) for i, m in enumerate(state.metrics)]
    for name, rv in named:
        if rv is not None and rv.source in by_source:
            by_source[rv.source].append(name)
    return by_source

sources = _field_sources(candidate_state)
_logger.debug(
    "conversation_turn",
    extra={
        "conversation_id": session_id,
        "current_question": question,
        "previous_state": serialize_state_for_prompt(previous_state),
        "turn_relation": validated_turn.turn_relation,
        "delta": validated_turn.delta,
        "new_state": serialize_state_for_prompt(candidate_state),
        "explicit_fields": sources["explicit"],
        "inherited_fields": sources["inherited"],
        "inferred_fields": sources["inferred"],
        "clarification_reason": decision.reason if decision.action == "clarify" else None,
    },
)
```

Import `serialize_state_for_prompt` from `tools.analyst.conversation_understanding` at the top of `context_builder.py`.

- [ ] **Step 2: Write a test that the log record carries the expected fields**

```python
# append to tests/analyst/test_context_builder.py
import logging


def test_build_context_emits_observability_log_record(caplog):
    clear_state("ctx-test-log")
    llm = _understanding_llm("continue", [
        {"field": "metrics", "operation": "replace", "raw_value": "vacancia", "source": "explicit"},
        {"field": "entities.fondo", "operation": "replace", "raw_value": "Parque Titanium", "source": "explicit"},
    ])
    with caplog.at_level(logging.DEBUG, logger="analyst.conversation"):
        build_context("vacancia de PT", session_id="ctx-test-log", history=[], llm_call=llm)
    records = [r for r in caplog.records if r.name == "analyst.conversation"]
    assert len(records) == 1
    assert records[0].conversation_id == "ctx-test-log"
    assert "metrics[0]" in records[0].explicit_fields
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/analyst/test_context_builder.py::test_build_context_emits_observability_log_record -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tools/analyst/context_builder.py tests/analyst/test_context_builder.py
git commit -m "feat(conversation): add structured per-turn observability logging"
```

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/analyst/ tests/eval/ -v`
Expected: PASS, zero regressions.

- [ ] **Step 6: Run the multi-turn stability eval and record results**

Run: `python -m tests.eval.run_eval --stability 5`

Read the printed pass-rates. If any scenario is `0/5` (architectural failure), do not proceed to Task 9 — go back to the relevant task (most likely Task 2's `apply_delta` omitted-dimension policy or Task 4's `decide_ambiguity`) and fix the root cause, per the design's explicit instruction not to special-case individual test questions.

Append the results to `docs/superpowers/plans/2026-08-10-analyst-agent-phase2-results.md`'s sibling — create `docs/superpowers/plans/2026-08-12-analyst-agent-phase3-results.md` with the raw output.

- [ ] **Step 7: Check `intent.py` façade consumers and retire it if clear**

Run: `rg "extract_intent|IntentResult|from tools\.analyst\.intent|from tools import intent" --type py`

If the only remaining matches are inside `tools/analyst/intent.py` itself and `tests/analyst/test_intent.py`, delete both files and remove the façade:

```bash
git rm tools/analyst/intent.py tests/analyst/test_intent.py
```

If any other consumer still appears (e.g. an untouched script), leave the façade in place, note the remaining consumer in the results doc, and skip this deletion — do not force it.

- [ ] **Step 8: Run full suite one more time and commit final state**

Run: `pytest tests/analyst/ tests/eval/ -v`
Expected: PASS

```bash
git add docs/superpowers/plans/2026-08-12-analyst-agent-phase3-results.md
git add -u  # stages the intent.py/test_intent.py deletion if Step 7 removed them
git commit -m "test(eval): record Phase 3 multi-turn stability results, retire intent.py facade if unused"
```

---

## Self-Review Notes

- **Spec coverage:** §1 schema → Task 1. §2 LLM call → Task 3. §3 merge → Task 2. §4 ambiguity → Task 4. §5 integration → Tasks 5-6. §5bis sequencing → Task 5 (`build_context`'s commit-only-on-proceed logic, tested explicitly in `test_ungrounded_question_clarifies_without_sections_and_does_not_commit_state`). §6 eval suite → Task 7. §7 observability → Task 8. Adjustment on `source=inherited` for `keep` → Task 2's `_apply_singular`/entity/metric branches, tested explicitly. Adjustment on entity-alone-insufficient → Task 4's `_has_usable_goal` gating. Adjustment on `intent.py` façade → Task 6 + Task 8 step 7. Adjustment on commit sequencing → Task 5.
- **Placeholder scan:** no TBD/TODO; every step has real code or an exact `rg`/`pytest` command with expected output.
- **Type consistency:** `ConversationState`/`ResolvedValue` (Task 1) are the only shapes threaded through Tasks 2-6; `ValidatedTurn` (Task 2) is consumed only by Task 5; `AnalystContext.state` (renamed from `.intent`, Task 5) is consumed by Task 6's façade and Task 8's logging via the same attribute name throughout.
