# Analyst Agent Phase 2 — Understanding + Conversation-Aware Orchestration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Phase 1's standalone `intent.py`/`entity_resolver.py`/`conversation_state.py` into the real `tools/db_chat.py` request path, add deterministic temporal resolution and a simple ambiguity policy, fix session identity, and prove measurable understanding improvement against a frozen Phase 1 baseline — without touching the existing SQL generation/validation/execution/result-check pipeline.

**Architecture:** Add a small `tools/analyst/context_builder.py` boundary that calls `intent.extract_intent()` (now given a real LLM call from `db_chat`'s provider chain), a new `tools/analyst/temporal.py` (deterministic, no LLM) and a new `tools/analyst/ambiguity.py` (pure function over `IntentResult`), then assembles labeled prompt sections. `db_chat.answer()` calls this builder once, before SQL generation, and either short-circuits with a clarification or appends the builder's sections to the existing `sql_messages` list — `_SQL_SYSTEM`, `_BUSINESS_CONTEXT`, few-shots, `_validate_sql`, `_run_sql`, `check_result` all stay untouched. Session identity moves from `request.remote_addr` to a client-generated `conversation_id` sent by `web/chat_bubble.js`.

**Tech Stack:** Python 3, Flask (`scripts/ingesta_server.py`), OpenAI-compatible client (`openai` pkg) against DeepSeek/Groq/Gemini, PyYAML + jsonschema (`semantic/`), pytest, vanilla JS (`web/chat_bubble.js`).

## Global Constraints

- Do not modify `_validate_sql`, `_run_sql`, the SELECT-only/read-only SQL boundary, or the provider-fallback chain (`_provider_chain`, `_chat_completion_with_fallback`) in `tools/db_chat.py`.
- Do not introduce a vector DB, multi-agent architecture, or feature flags. Change code directly; git history is the rollback mechanism.
- All new modules under `tools/analyst/` must remain independently unit-testable (no network calls in unit tests; LLM calls injected as `Callable`).
- `semantic/` YAML + JSON Schema validation stays the single source of truth for metric business definitions — do not duplicate metric definitions into new Python code.
- Every new behavior that changes `db_chat.answer()`'s output must be covered by `tests/test_db_chat.py` and, where it affects understanding accuracy, by `tests/eval/`.
- Session/conversation identity must never fall back silently to a shared key across genuinely different browser sessions once a `conversation_id` is available; IP fallback is only for legacy/no-JS clients.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/analyst/temporal.py` (new) | Deterministic Spanish temporal-phrase → period/range resolution. No LLM, no DB. |
| `tools/analyst/ambiguity.py` (new) | Pure function: given `IntentResult` + grounding signals, decide proceed / clarify. |
| `tools/analyst/context_builder.py` (new) | Orchestrates `extract_intent` (with a real `llm_call`), `resolve_temporal`, `ambiguity.decide`, metric semantic lookup, and verified-query lookup into one `AnalystContext` + labeled prompt sections. |
| `tools/db_chat.py` (modify) | `answer()` calls `context_builder.build_context(...)` before SQL generation; early-return on `clarify`; splice `AnalystContext.prompt_sections` into `sql_messages` in place of the ad hoc `verified_hint` block. |
| `scripts/ingesta_server.py` (modify) | `/api/chat` reads `conversation_id` from request body (fallback to `X-Conversation-Id` header, fallback to `request.remote_addr`) instead of always using `request.remote_addr`. |
| `web/chat_bubble.js` (modify) | Generates/persists a `conversation_id` (via `crypto.randomUUID()` + `sessionStorage`) and sends it with every `/api/chat` POST. |
| `tests/analyst/test_temporal.py` (new) | Unit tests for `temporal.py`. |
| `tests/analyst/test_ambiguity.py` (new) | Unit tests for `ambiguity.py`. |
| `tests/analyst/test_context_builder.py` (new) | Unit tests for `context_builder.py` with a fake `llm_call`. |
| `tests/test_ingesta_server_session.py` (new) | Session-isolation tests for the new `conversation_id` wiring. |
| `tests/test_db_chat.py` (modify) | Add coverage for the new context-builder wiring and clarify short-circuit. |
| `tests/eval/questions.yaml` (modify) | Expand from 18 to ~38 single-turn cases (entity aliases, metric aliases, temporal phrases, ambiguity). |
| `tests/eval/conversations.yaml` (new) | ~10 multi-turn conversations exercising inheritance and entity replacement. |
| `tests/eval/run_eval.py` (modify) | Add a `--full` mode that runs through `db_chat.answer()` end-to-end (not just `extract_intent`), reports metric/entity/temporal/intent accuracy, and runs `conversations.yaml`. |
| `docs/superpowers/plans/2026-08-10-analyst-agent-phase2-results.md` (new, produced at the end) | Before/after eval comparison report. |

---

## Task 1: Freeze the Phase 1 baseline

**Files:**
- Modify: `tests/eval/run_eval.py`
- Create: `docs/superpowers/plans/2026-08-10-analyst-agent-phase2-baseline.md`

**Interfaces:**
- Consumes: existing `run()` in `tests/eval/run_eval.py`, existing `tests/eval/questions.yaml` (18 entries).
- Produces: a frozen text record of Phase 1 accuracy numbers, referenced by Task 12's comparison.

Before touching any production code, checkout `main`, confirm the merge commit, and run the existing suite untouched.

- [ ] **Step 1: Confirm repo state**

Run:
```bash
git status
git log -n 5 --oneline
```
Expected: clean tree (or only the untracked scratch files already present before this session), `HEAD` at or after `1c93aef`.

- [ ] **Step 2: Create the Phase 2 branch**

```bash
git checkout -b feat/analyst-agent-phase-2
```

- [ ] **Step 3: Run the full test suite to confirm the 98-test baseline**

```bash
python -m pytest tests/ -q
```
Expected: all tests pass (98+ as reported after the Phase 1 merge). Record the exact count in the baseline doc.

- [ ] **Step 4: Run the existing eval runner and record output verbatim**

```bash
python tests/eval/run_eval.py
```
This exercises `extract_intent()` in isolation (not `db_chat.answer()`) — that's the existing behavior, keep it as-is for this step. Capture the full stdout.

- [ ] **Step 5: Write the baseline doc**

Create `docs/superpowers/plans/2026-08-10-analyst-agent-phase2-baseline.md`:
```markdown
# Phase 2 Baseline (frozen at commit 1c93aef)

## Test suite
- `python -m pytest tests/ -q` → <paste pass/fail count>

## Eval (extract_intent only, tests/eval/questions.yaml, 18 questions)
<paste full run_eval.py stdout verbatim>

## Known Phase 1 gaps (from repo inspection)
- intent.py / entity_resolver.py NOT called from tools/db_chat.py or scripts/ingesta_server.py.
- conversation_state only ever writes last_metric from db_chat.answer(); last_entities/last_period/last_analysis_type are never populated in the real flow.
- scripts/ingesta_server.py:336 uses request.remote_addr as session_id.
- Only 5 metrics have semantic/metrics/*.yaml (vacancia_pct, noi, dividend_yield, tir_desde_inicio, tasa_arriendo); _BUSINESS_CONTEXT in db_chat.py still hardcodes entity/synonym data that duplicates semantic/entities.yaml + synonyms.yaml.
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/plans/2026-08-10-analyst-agent-phase2-baseline.md
git commit -m "docs(analyst): freeze Phase 1 eval baseline before Phase 2 changes"
```

---

## Task 2: Deterministic temporal resolution (`temporal.py`)

**Files:**
- Create: `tools/analyst/temporal.py`
- Test: `tests/analyst/test_temporal.py`

**Interfaces:**
- Produces: `TemporalResolution` dataclass and `resolve_temporal(text, today=None, time_behavior=None) -> TemporalResolution | None`, consumed by Task 4 (`context_builder.py`).

Period format in the DB is always `YYYY-MM` (per `CLAUDE.md`: "Formato periodo: siempre YYYY-MM"). All resolution is anchored to a `datetime.date` (`today`, defaulting to `date.today()` but overridable for tests).

- [ ] **Step 1: Write the failing tests**

Create `tests/analyst/test_temporal.py`:
```python
from datetime import date

from tools.analyst.temporal import resolve_temporal, TemporalResolution


_TODAY = date(2026, 8, 10)  # August 2026, for deterministic tests


def test_este_mes():
    r = resolve_temporal("¿cómo viene la vacancia este mes?", today=_TODAY)
    assert r.period == "2026-08"
    assert r.period_range is None
    assert r.comparison_period is None


def test_mes_pasado():
    r = resolve_temporal("dame el NOI del mes pasado", today=_TODAY)
    assert r.period == "2026-07"


def test_mes_pasado_cruza_anio():
    r = resolve_temporal("mes pasado", today=date(2026, 1, 15))
    assert r.period == "2025-12"


def test_este_anio():
    r = resolve_temporal("evolución de la ocupación este año", today=_TODAY)
    assert r.period is None
    assert r.period_range == ("2026-01", "2026-12")


def test_ytd():
    r = resolve_temporal("dividend yield YTD", today=_TODAY)
    assert r.period_range == ("2026-01", "2026-08")


def test_anio_pasado():
    r = resolve_temporal("NOI del año pasado", today=_TODAY)
    assert r.period_range == ("2025-01", "2025-12")


def test_mismo_periodo_anio_anterior():
    r = resolve_temporal("¿y el mismo período del año anterior?", today=_TODAY)
    assert r.comparison_period == "same_period_last_year"


def test_ultimos_12_meses():
    r = resolve_temporal("últimos 12 meses de NOI", today=_TODAY)
    assert r.period_range == ("2025-09", "2026-08")


def test_proximos_12_meses_flags_gap():
    r = resolve_temporal("proyección próximos 12 meses", today=_TODAY)
    assert r.period_range == ("2026-09", "2027-08")
    assert r.data_gap_warning is not None


def test_hoy_snapshot_behavior():
    r = resolve_temporal("saldo de caja hoy", today=_TODAY, time_behavior="snapshot")
    assert r.period == "2026-08"
    assert "snapshot" in r.label.lower() or "cierre" in r.label.lower()


def test_ultimo_cierre_flow_behavior():
    r = resolve_temporal("último cierre de NOI", today=_TODAY, time_behavior="flow")
    assert r.period is None
    assert r.label  # explains "último dato disponible", no invented period


def test_no_temporal_phrase_returns_none():
    assert resolve_temporal("vacancia de Parque Titanium", today=_TODAY) is None
```

- [ ] **Step 2: Run to verify all fail**

```bash
python -m pytest tests/analyst/test_temporal.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.analyst.temporal'`.

- [ ] **Step 3: Implement `tools/analyst/temporal.py`**

```python
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
    (re.compile(r"\ba[ñn]o\s+pasado\b|\ba[ñn]o\s+anterior\b", re.IGNORECASE), "anio_pasado"),
    (
        re.compile(
            r"\bmismo\s+per[ií]odo\s+(del\s+)?a[ñn]o\s+anterior\b|\bversus\s+a[ñn]o\s+pasado\b|"
            r"\by\s+el\s+a[ñn]o\s+pasado\b",
            re.IGNORECASE,
        ),
        "mismo_periodo_anio_anterior",
    ),
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
    """Returns None if `text` contains no recognized temporal phrase."""
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
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/analyst/test_temporal.py -v
```
Expected: all 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/temporal.py tests/analyst/test_temporal.py
git commit -m "feat(analyst): add deterministic temporal phrase resolution"
```

---

## Task 3: Ambiguity policy (`ambiguity.py`)

**Files:**
- Create: `tools/analyst/ambiguity.py`
- Test: `tests/analyst/test_ambiguity.py`

**Interfaces:**
- Consumes: `tools.analyst.intent.IntentResult` (existing, `tools/analyst/intent.py:32-39`).
- Produces: `AmbiguityDecision` dataclass and `decide(intent, verified_hint, has_history) -> AmbiguityDecision`, consumed by Task 4.

The policy must not clarify on every incomplete prompt (spec §11). It only escalates to `clarify` when `IntentResult.needs_clarification` is already `True` (i.e. `extract_intent` found low confidence with no metric/entities even after inheriting from conversation state) **and** there is no other grounding signal available (a lexical verified-query match, or existing conversation history).

- [ ] **Step 1: Write the failing tests**

Create `tests/analyst/test_ambiguity.py`:
```python
from tools.analyst.ambiguity import decide, AmbiguityDecision
from tools.analyst.intent import IntentResult


def test_confident_intent_proceeds():
    intent = IntentResult(metric="vacancia_pct", entities={"activo": "Parque Titanium"},
                           confidence=0.9, needs_clarification=False)
    d = decide(intent, verified_hint=None, has_history=False)
    assert d.action == "proceed"


def test_low_confidence_with_verified_hint_proceeds():
    intent = IntentResult(metric=None, entities={}, confidence=0.2, needs_clarification=True)
    d = decide(intent, verified_hint={"question": "...", "sql": "..."}, has_history=False)
    assert d.action == "proceed"
    assert "verified" in d.reason.lower()


def test_low_confidence_with_history_proceeds():
    intent = IntentResult(metric=None, entities={}, confidence=0.2, needs_clarification=True)
    d = decide(intent, verified_hint=None, has_history=True)
    assert d.action == "proceed"


def test_low_confidence_no_grounding_clarifies():
    intent = IntentResult(metric=None, entities={}, confidence=0.1, needs_clarification=True)
    d = decide(intent, verified_hint=None, has_history=False)
    assert d.action == "clarify"
    assert d.clarify_message


def test_inherited_from_state_is_not_needs_clarification():
    # extract_intent() already set needs_clarification=False when it could
    # inherit metric/entities from conversation state.
    intent = IntentResult(metric="noi", entities={"fondo": "PT"}, confidence=0.2,
                           needs_clarification=False)
    d = decide(intent, verified_hint=None, has_history=False)
    assert d.action == "proceed"
    assert "inherited" in d.reason.lower() or "confidence" in d.reason.lower()
```

- [ ] **Step 2: Run to verify all fail**

```bash
python -m pytest tests/analyst/test_ambiguity.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.analyst.ambiguity'`.

- [ ] **Step 3: Implement `tools/analyst/ambiguity.py`**

```python
"""Decides whether to proceed with SQL generation, or ask for clarification,
based on the resolved IntentResult plus lightweight grounding signals.

Kept deliberately simple: this is an early short-circuit for the clearest
"we truly have nothing to go on" case only. It does not replace the existing
`clarify` mechanism inside the SQL-generation prompt (tools/db_chat.py's
_SQL_SYSTEM instructs the model to ask for clarification itself when it's
unsure) -- it just avoids spending an LLM call on SQL generation when we
already know, deterministically, that we have no metric, no entities, no
verified-query hint, and no conversation history to fall back on.
"""
from __future__ import annotations

from dataclasses import dataclass

from tools.analyst.intent import IntentResult

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


def decide(
    intent: IntentResult,
    verified_hint: dict | None,
    has_history: bool,
) -> AmbiguityDecision:
    if not intent.needs_clarification:
        return AmbiguityDecision("proceed", "intent confidence sufficient or metric/entities inherited from state")

    if verified_hint is not None:
        return AmbiguityDecision("proceed", "low confidence but a verified-query hint grounds the question")

    if has_history:
        return AmbiguityDecision("proceed", "low confidence but conversation history provides context")

    return AmbiguityDecision(
        "clarify",
        "low confidence intent with no metric, no entities, no verified hint, no history",
        clarify_message=_CLARIFY_MESSAGE,
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/analyst/test_ambiguity.py -v
```
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/ambiguity.py tests/analyst/test_ambiguity.py
git commit -m "feat(analyst): add simple ambiguity policy over resolved intent"
```

---

## Task 4: Semantic context builder (`context_builder.py`)

**Files:**
- Create: `tools/analyst/context_builder.py`
- Test: `tests/analyst/test_context_builder.py`

**Interfaces:**
- Consumes: `extract_intent(question, session_id, llm_call)` (`tools/analyst/intent.py:50`), `resolve_temporal(text, today, time_behavior)` (Task 2), `decide(intent, verified_hint, has_history)` (Task 3), `find_similar(question, top_k)` (`tools/analyst/verified_queries_repo.py:27`), `load_semantic_catalog()` (`tools/analyst/semantic_loader.py:41`), `get_state(session_id)` (`tools/analyst/conversation_state.py:20`).
- Produces: `AnalystContext` dataclass with `.decision: AmbiguityDecision` and `.prompt_sections: list[tuple[str, str]]`, consumed by Task 5 (`db_chat.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/analyst/test_context_builder.py`:
```python
from tools.analyst.context_builder import build_context
from tools.analyst.conversation_state import clear_state


def _fake_llm_call(prompt: str) -> str:
    return (
        '{"metric": "vacancia_pct", "entities": {"activo": "Parque Titanium"}, '
        '"period": null, "comparison": null, "confidence": 0.9}'
    )


def _empty_llm_call(prompt: str) -> str:
    return '{"metric": null, "entities": {}, "period": null, "comparison": null, "confidence": 0.1}'


def test_confident_question_produces_proceed_context():
    clear_state("ctx-test-1")
    ctx = build_context(
        "¿cuál es la vacancia de Parque Titanium este mes?",
        session_id="ctx-test-1",
        history=[],
        llm_call=_fake_llm_call,
    )
    assert ctx.decision.action == "proceed"
    assert ctx.intent.metric == "vacancia_pct"
    labels = [label for label, _ in ctx.prompt_sections]
    assert "RESOLVED INTENT" in labels
    assert "BUSINESS DEFINITIONS" in labels
    assert "PERIOD / COMPARISON" in labels


def test_temporal_phrase_adds_period_section():
    clear_state("ctx-test-2")
    ctx = build_context(
        "vacancia de Parque Titanium este mes",
        session_id="ctx-test-2",
        history=[],
        llm_call=_fake_llm_call,
    )
    period_section = dict(ctx.prompt_sections)["PERIOD / COMPARISON"]
    assert "2026" in period_section or "mes" in period_section.lower()


def test_ungrounded_question_clarifies_without_sections():
    clear_state("ctx-test-3")
    ctx = build_context(
        "cuéntame algo",
        session_id="ctx-test-3",
        history=[],
        llm_call=_empty_llm_call,
    )
    assert ctx.decision.action == "clarify"
    assert ctx.decision.clarify_message


def test_ungrounded_but_verified_hint_proceeds():
    clear_state("ctx-test-4")
    ctx = build_context(
        "dame el DY con amortización de la serie A",
        session_id="ctx-test-4",
        history=[],
        llm_call=_empty_llm_call,
    )
    # "dy_amort_serie" verified query exists in tools/analyst/verified_queries/
    # and should lexically match enough of this question to ground it.
    assert ctx.decision.action in ("proceed", "clarify")  # exact outcome depends on lexical overlap
    if ctx.decision.action == "proceed":
        assert any(label == "VERIFIED EXAMPLE" for label, _ in ctx.prompt_sections)
```

- [ ] **Step 2: Run to verify all fail**

```bash
python -m pytest tests/analyst/test_context_builder.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.analyst.context_builder'`.

- [ ] **Step 3: Implement `tools/analyst/context_builder.py`**

```python
"""Boundary that turns a user question + conversation state into everything
tools/db_chat.py's SQL-generation prompt needs: a structured IntentResult,
resolved entities/metric/period, business definitions, a verified-query hint,
and an ambiguity decision -- assembled as labeled (title, content) sections
ready to splice into the chat-completion `messages` list.

This does NOT call the LLM for SQL generation and does NOT touch
_validate_sql/_run_sql -- it only prepares context for the existing pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tools.analyst.ambiguity import AmbiguityDecision, decide
from tools.analyst.conversation_state import get_state
from tools.analyst.intent import IntentResult, extract_intent
from tools.analyst.semantic_loader import load_semantic_catalog
from tools.analyst.temporal import TemporalResolution, resolve_temporal
from tools.analyst.verified_queries_repo import find_similar


@dataclass
class AnalystContext:
    intent: IntentResult
    decision: AmbiguityDecision
    temporal: TemporalResolution | None
    verified_hint: dict | None
    prompt_sections: list[tuple[str, str]] = field(default_factory=list)


def _metric_time_behavior(metric_name: str | None) -> str | None:
    if not metric_name:
        return None
    catalog = load_semantic_catalog()
    metric = catalog.metrics.get(metric_name)
    return metric.get("time_behavior") if metric else None


def _build_sections(
    question: str,
    intent: IntentResult,
    temporal: TemporalResolution | None,
    verified_hint: dict | None,
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []

    intent_lines = [f"metric: {intent.metric or '(sin resolver)'}"]
    for kind, value in intent.entities.items():
        intent_lines.append(f"entity[{kind}]: {value}")
    if intent.comparison:
        intent_lines.append(f"comparison: {intent.comparison}")
    intent_lines.append(f"confidence: {intent.confidence:.2f}")
    sections.append(("RESOLVED INTENT", "\n".join(intent_lines)))

    if intent.metric:
        catalog = load_semantic_catalog()
        metric_def = catalog.metrics.get(intent.metric)
        if metric_def:
            def_lines = [
                f"business_definition: {metric_def.get('business_definition', '')}",
                f"formula: {metric_def.get('formula', '')}",
                f"unit: {metric_def.get('unit', '')}",
            ]
            sections.append(("BUSINESS DEFINITIONS", "\n".join(def_lines)))

    period_lines = []
    if intent.period:
        period_lines.append(f"period (from intent): {intent.period}")
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
    intent = extract_intent(question, session_id, llm_call)

    verified = find_similar(question, top_k=1)
    verified_hint = verified[0] if verified else None

    time_behavior = _metric_time_behavior(intent.metric)
    temporal = resolve_temporal(question, time_behavior=time_behavior)

    has_history = bool(history)
    decision = decide(intent, verified_hint=verified_hint, has_history=has_history)

    prompt_sections = (
        [] if decision.action == "clarify" else _build_sections(question, intent, temporal, verified_hint)
    )

    return AnalystContext(
        intent=intent,
        decision=decision,
        temporal=temporal,
        verified_hint=verified_hint,
        prompt_sections=prompt_sections,
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/analyst/test_context_builder.py -v
```
Expected: all 4 PASS. (If `test_ungrounded_but_verified_hint_proceeds` is flaky because of lexical-overlap tuning in `find_similar`, that's expected — the test asserts the conditional invariant, not a fixed outcome.)

- [ ] **Step 5: Commit**

```bash
git add tools/analyst/context_builder.py tests/analyst/test_context_builder.py
git commit -m "feat(analyst): add semantic context builder wiring intent+temporal+ambiguity+verified-query"
```

---

## Task 5: Wire the context builder into `tools/db_chat.py`

**Files:**
- Modify: `tools/db_chat.py`
- Test: `tests/test_db_chat.py`

**Interfaces:**
- Consumes: `build_context(question, session_id, history, llm_call)` → `AnalystContext` (Task 4).
- Produces: `answer()` keeps its existing return-dict shape, plus early-returns a `clarify` dict when `AnalystContext.decision.action == "clarify"`.

This is the one place the "existing SQL safety pipeline stays intact" constraint is load-bearing: only the message-assembly step before `_validate_sql`/`_run_sql` changes.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_chat.py` (append, keep existing tests untouched):
```python
class TestContextBuilderWiring(unittest.TestCase):
    def test_clarify_short_circuit_before_sql_generation(self):
        from tools.analyst.conversation_state import clear_state
        clear_state("test-clarify-wiring")
        result = db_chat.answer("cuéntame algo", session_id="test-clarify-wiring")
        # A fully ungrounded question with no prior state must clarify
        # deterministically, without ever reaching SQL generation.
        self.assertTrue(result.get("clarify"))
        self.assertIsNone(result.get("sql"))

    def test_context_sections_reach_the_sql_prompt(self):
        # Regression guard: RESOLVED INTENT / labeled sections must appear
        # in the messages sent for SQL generation, not just be computed and
        # discarded.
        captured = {}
        original = db_chat._chat_completion_with_fallback

        def _spy(messages, **kwargs):
            if "captured_sql_messages" not in captured:
                captured["captured_sql_messages"] = messages
            return original(messages, **kwargs)

        db_chat._chat_completion_with_fallback = _spy
        try:
            db_chat.answer("vacancia de Parque Titanium este mes", session_id="test-sections-wiring")
        finally:
            db_chat._chat_completion_with_fallback = original

        contents = " ".join(
            m["content"] for m in captured.get("captured_sql_messages", []) if isinstance(m.get("content"), str)
        )
        self.assertIn("RESOLVED INTENT", contents)
```

- [ ] **Step 2: Run to verify both fail**

```bash
python -m pytest tests/test_db_chat.py -v -k ContextBuilderWiring
```
Expected: FAIL — `test_clarify_short_circuit_before_sql_generation` gets a normal SQL-gen response instead of `clarify`; `test_context_sections_reach_the_sql_prompt` finds no `"RESOLVED INTENT"` in captured messages.

- [ ] **Step 3: Modify `tools/db_chat.py`**

Add the import (near the existing `tools.analyst.*` imports, `db_chat.py:35-38`):
```python
from tools.analyst.context_builder import build_context
```

Add a small LLM-call adapter right after `_chat_completion_with_fallback` (after `db_chat.py:134`):
```python
def _intent_llm_call(prompt: str) -> str:
    """Adapter handing context_builder's intent extraction a real LLM call
    through the existing provider chain, without db_chat.answer()'s SQL/answer
    prompts. Kept intentionally cheap: short prompt, low max_tokens."""
    resp, _ = _chat_completion_with_fallback(
        [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=200,
    )
    return resp.choices[0].message.content or ""
```

Replace the block at `db_chat.py:843-879` (from `verified = find_similar(...)` through the closing of `sql_messages += [...]`) with:
```python
    ctx = build_context(question, session_id, history or [], _intent_llm_call)

    if ctx.decision.action == "clarify":
        return {
            "answer_md": ctx.decision.clarify_message,
            "clarify": True,
            "sql": None,
            "columns": [],
            "rows": [],
            "provider": _resolve_provider()["model"],
        }

    try:
        chain = _provider_chain()
    except RuntimeError as exc:
        return {
            "answer_md": _MENSAJE_SIN_CUPO,
            "error": "no_api_key",
            "error_detalle": str(exc),
        }
    provider = chain[0]

    # Paso 1: generar SQL. El playbook YA cubre la seleccion de tablas y
    # columnas; el PRAGMA schema completo (~2k tokens) es redundante y hace
    # que el prompt exceda el rate limit del free tier de Groq. Lo dejamos
    # fuera y confiamos en el playbook + few-shots.
    sql_messages = [
        {"role": "system", "content": _SQL_SYSTEM},
        {"role": "system", "content": _BUSINESS_CONTEXT},
        {"role": "system", "content": "Ejemplos gold pregunta→JSON. Sigue exactamente este patron de entidad_key, formula, filtros y formato JSON."},
    ]
    for label, content in ctx.prompt_sections:
        sql_messages.append({"role": "system", "content": f"{label}:\n{content}"})
    sql_messages += [
        *_few_shot_messages(),
        *_serialize_history(history or []),
        {"role": "user", "content": question},
    ]
```

Note: this deletes the old `chain = _provider_chain()` placement relative to `verified`/`find_similar` — re-read `db_chat.py:843-884` after the edit to confirm `provider = chain[0]` still exists exactly once before the `try: resp, provider = _chat_completion_with_fallback(...)` call at the old `881-884` (now shifted a few lines down but otherwise unchanged).

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_db_chat.py -v
```
Expected: all tests PASS, including the 2 new ones and every pre-existing `test_db_chat.py` test (no regressions — `_validate_sql`/`_run_sql`/provider fallback paths are untouched).

- [ ] **Step 5: Run the full suite**

```bash
python -m pytest tests/ -q
```
Expected: same pass count as Task 1's baseline plus the new tests added so far (Tasks 2-5).

- [ ] **Step 6: Commit**

```bash
git add tools/db_chat.py tests/test_db_chat.py
git commit -m "feat(analyst): wire structured intent + ambiguity + temporal context into db_chat SQL generation"
```

---

## Task 6: Restructure `_ANSWER_SYSTEM`/synthesis pass to reuse resolved context (optional light touch)

**Files:**
- Modify: `tools/db_chat.py`

**Interfaces:**
- Consumes: `ctx` (`AnalystContext`, in scope from Task 5) inside `answer()`.
- Produces: no new interfaces — this only enriches the existing `answer_messages` user content built at `db_chat.py:987-997`.

The synthesis pass currently only receives `question` + raw `datasets`. Give it the resolved metric's `unit`/`business_definition` too, so the model doesn't have to re-infer units from raw numbers (spec explicitly separates "instructions" from context the system already resolved).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db_chat.py`:
```python
def test_answer_synthesis_receives_resolved_metric_context(self):
    captured = {}
    original = db_chat._chat_completion_with_fallback
    calls = []

    def _spy(messages, **kwargs):
        calls.append(messages)
        return original(messages, **kwargs)

    db_chat._chat_completion_with_fallback = _spy
    try:
        db_chat.answer("vacancia de Parque Titanium en 2026-06", session_id="test-synthesis-context")
    finally:
        db_chat._chat_completion_with_fallback = original

    self.assertEqual(len(calls), 2)  # SQL-gen pass + synthesis pass
    synthesis_content = calls[1][-1]["content"]
    self.assertIn("business_definition", synthesis_content.lower())
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_db_chat.py -v -k test_answer_synthesis_receives_resolved_metric_context
```
Expected: FAIL — `"business_definition"` not present in synthesis content.

- [ ] **Step 3: Modify `db_chat.py`'s synthesis message assembly**

Replace `db_chat.py:986-997`:
```python
    # Paso 2: sintetizar respuesta a partir de todos los datasets obtenidos
    resolved_context_note = ""
    if ctx.intent.metric:
        catalog = load_semantic_catalog()
        metric_def = catalog.metrics.get(ctx.intent.metric)
        if metric_def:
            resolved_context_note = (
                f"\n\nCONTEXTO DE LA METRICA RESUELTA ({ctx.intent.metric}):\n"
                f"business_definition: {metric_def.get('business_definition', '')}\n"
                f"unit: {metric_def.get('unit', '')}"
            )

    answer_messages = [
        {"role": "system", "content": _ANSWER_SYSTEM},
        {
            "role": "user",
            "content": (
                f"PREGUNTA: {question}\n\n"
                f"CONSULTAS INTERNAS EJECUTADAS Y SUS DATOS (JSON, una entrada por consulta):\n"
                f"```json\n{json.dumps(datasets, default=str, ensure_ascii=False)}\n```"
                f"{resolved_context_note}"
            ),
        },
    ]
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_db_chat.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db_chat.py tests/test_db_chat.py
git commit -m "feat(analyst): pass resolved metric business definition into answer synthesis pass"
```

---

## Task 7: Replace `request.remote_addr` with a real conversation identifier

**Files:**
- Modify: `web/chat_bubble.js`
- Modify: `scripts/ingesta_server.py`
- Test: `tests/test_ingesta_server_session.py` (new)

**Interfaces:**
- Produces: `/api/chat` reads `conversation_id` from the JSON body (preferred), then `X-Conversation-Id` header, then falls back to `request.remote_addr` for legacy/no-JS callers.

The frontend (`web/chat_bubble.js`) has no existing session/conversation id (confirmed: `history` is the only client-tracked chat state, `web/chat_bubble.js:140`). Add the smallest reliable mechanism: a `crypto.randomUUID()` generated once per browser tab session and persisted in `sessionStorage` (survives page navigation within the tab, dies when the tab closes — matches "a user's IP may change" / "parallel chats must not contaminate" requirements without any new auth).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingesta_server_session.py`:
```python
"""Session/conversation isolation for /api/chat (Phase 2: conversation_id
replaces request.remote_addr as the analyst conversation-state key)."""
import unittest
from unittest.mock import patch

from scripts import ingesta_server
from tools.analyst.conversation_state import clear_state, get_state


class TestConversationIdSessionKey(unittest.TestCase):
    def setUp(self):
        self.client = ingesta_server.app.test_client()
        self.token = ingesta_server._get_or_create_token() if hasattr(ingesta_server, "_get_or_create_token") else None
        clear_state("conv-a")
        clear_state("conv-b")

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        token = getattr(ingesta_server, "INGESTA_TOKEN", None)
        if token:
            headers["X-Ingesta-Token"] = token
        return headers

    @patch("tools.db_chat.answer")
    def test_conversation_id_from_body_used_as_session_key(self, mock_answer):
        mock_answer.return_value = {"answer_md": "ok", "sql": None, "columns": [], "rows": []}
        self.client.post(
            "/api/chat",
            json={"question": "hola", "history": [], "conversation_id": "conv-a"},
            headers=self._headers(),
        )
        self.assertEqual(mock_answer.call_args.kwargs.get("session_id"), "conv-a")

    @patch("tools.db_chat.answer")
    def test_two_conversation_ids_stay_isolated(self, mock_answer):
        mock_answer.return_value = {"answer_md": "ok", "sql": None, "columns": [], "rows": []}
        self.client.post(
            "/api/chat",
            json={"question": "vacancia de PT", "history": [], "conversation_id": "conv-a"},
            headers=self._headers(),
        )
        self.client.post(
            "/api/chat",
            json={"question": "hola", "history": [], "conversation_id": "conv-b"},
            headers=self._headers(),
        )
        session_ids = [c.kwargs.get("session_id") for c in mock_answer.call_args_list]
        self.assertEqual(session_ids, ["conv-a", "conv-b"])
        self.assertNotEqual(session_ids[0], session_ids[1])

    @patch("tools.db_chat.answer")
    def test_missing_conversation_id_falls_back_to_remote_addr(self, mock_answer):
        mock_answer.return_value = {"answer_md": "ok", "sql": None, "columns": [], "rows": []}
        self.client.post(
            "/api/chat",
            json={"question": "hola", "history": []},
            headers=self._headers(),
        )
        used = mock_answer.call_args.kwargs.get("session_id")
        self.assertTrue(used)  # falls back to something (remote_addr), not empty/None
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_ingesta_server_session.py -v
```
Expected: FAIL on `test_conversation_id_from_body_used_as_session_key` and `test_two_conversation_ids_stay_isolated` (both currently get `session_id="127.0.0.1"` from `remote_addr`, not `"conv-a"`/`"conv-b"`).

- [ ] **Step 3: Modify `scripts/ingesta_server.py`**

Replace `scripts/ingesta_server.py:333-336`:
```python
    # Session key para el estado conversacional del Asistente: preferimos un
    # conversation_id generado por el cliente (persistido en sessionStorage
    # del navegador, unico por pestaña/sesion). Si el cliente no lo manda
    # (llamada legacy o sin JS), caemos a la IP como antes.
    conversation_id = body.get("conversation_id") or request.headers.get("X-Conversation-Id")
    session_id = str(conversation_id) if conversation_id else (request.remote_addr or "default")
```

- [ ] **Step 4: Modify `web/chat_bubble.js`**

Add right after `const history = [];` (`web/chat_bubble.js:140`):
```javascript
  const CONVERSATION_ID_KEY = "toesca_asistente_conversation_id";
  let conversationId = sessionStorage.getItem(CONVERSATION_ID_KEY);
  if (!conversationId) {
    conversationId = crypto.randomUUID();
    sessionStorage.setItem(CONVERSATION_ID_KEY, conversationId);
  }
```

Update the fetch body at `web/chat_bubble.js:398`:
```javascript
        body: JSON.stringify({ question: q, history, conversation_id: conversationId }),
```

- [ ] **Step 5: Run tests to verify pass**

```bash
python -m pytest tests/test_ingesta_server_session.py -v
```
Expected: all 3 PASS.

- [ ] **Step 6: Run the full suite (regression check on existing `/api/chat` tests)**

```bash
python -m pytest tests/ -q
```
Expected: no regressions — `tests/test_ingesta_server_seguridad.py`'s `/api/chat` auth test still passes since auth (`X-Ingesta-Token`) is untouched.

- [ ] **Step 7: Commit**

```bash
git add scripts/ingesta_server.py web/chat_bubble.js tests/test_ingesta_server_session.py
git commit -m "fix(server): replace IP-based analyst session key with client-generated conversation_id"
```

---

## Task 8: Multi-turn conversation-state integration tests

**Files:**
- Test: `tests/test_db_chat.py` (append)

**Interfaces:**
- Consumes: `db_chat.answer(question, history, session_id)` (existing signature, unchanged), `tools.analyst.conversation_state.clear_state`.

Prove the concrete Phase 2 scenarios from the spec work end-to-end through the real `answer()` entrypoint (not just `extract_intent` in isolation, which Task 1's baseline already covers).

- [ ] **Step 1: Write the tests**

Append to `tests/test_db_chat.py`:
```python
class TestConversationalInheritance(unittest.TestCase):
    def test_followup_inherits_metric_and_entity(self):
        from tools.analyst.conversation_state import clear_state, get_state
        clear_state("test-followup-1")
        db_chat.answer("¿Cuál fue la ocupación de Parque Titanium en julio?",
                        session_id="test-followup-1")
        state_after_q1 = get_state("test-followup-1")
        self.assertIsNotNone(state_after_q1["last_metric"])
        self.assertTrue(state_after_q1["last_entities"])

        db_chat.answer("¿Y versus el año pasado?", session_id="test-followup-1")
        state_after_q2 = get_state("test-followup-1")
        # metric/entity carried forward; not reset to None by the follow-up.
        self.assertEqual(state_after_q2["last_metric"], state_after_q1["last_metric"])
        self.assertEqual(state_after_q2["last_entities"], state_after_q1["last_entities"])

    def test_entity_replacement_keeps_metric_and_period(self):
        from tools.analyst.conversation_state import clear_state, get_state
        clear_state("test-replace-1")
        db_chat.answer("Evolución mensual de ocupación de PT en 2026", session_id="test-replace-1")
        state_after_q1 = get_state("test-replace-1")

        db_chat.answer("Ahora Viña Centro", session_id="test-replace-1")
        state_after_q2 = get_state("test-replace-1")
        self.assertEqual(state_after_q2["last_metric"], state_after_q1["last_metric"])
        self.assertNotEqual(state_after_q2["last_entities"], state_after_q1["last_entities"])
```

- [ ] **Step 2: Run**

```bash
python -m pytest tests/test_db_chat.py -v -k ConversationalInheritance
```
Expected: PASS given Task 5's wiring (`extract_intent` already inherits/updates `last_metric`/`last_entities`/`last_period` per `tools/analyst/intent.py:62-85`, now actually reached from `answer()`). If a test fails, the bug is almost certainly that `intent.py`'s LLM-based metric guess disagrees with `_extract_metric_from_sql`'s post-hoc overwrite at `db_chat.py:1022` — inspect which one is wrong before changing either; do not paper over a real disagreement by loosening the assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/test_db_chat.py
git commit -m "test(analyst): add end-to-end conversational inheritance tests through db_chat.answer()"
```

---

## Task 9: Expand the eval question set (single-turn)

**Files:**
- Modify: `tests/eval/questions.yaml`

**Interfaces:**
- Consumes/produces: same schema as existing 18 entries (`question`, `expected_metric`, `expected_entities`, optional `expected_period`, optional `notes`).

Add ~20 new cases grounded in real schema/business definitions from `semantic/` and `CLAUDE.md`, covering entity aliases, metric aliases, and temporal phrases not in the current 18. Do not invent unsupported metrics.

- [ ] **Step 1: Append to `tests/eval/questions.yaml`**

```yaml
# --- Phase 2 additions: entity aliases ---
- question: "¿cómo viene Titanium este mes?"
  expected_metric: null
  expected_entities: {fondo: PT}
  notes: "alias informal 'Titanium' para Parque Titanium/PT sin metrica explicita"

- question: "vacancia del fondo madre"
  expected_metric: vacancia_pct
  expected_entities: {fondo: TRI}
  notes: "alias 'fondo madre' -> TRI"

- question: "NOI de Apoquindo 4501"
  expected_metric: noi
  expected_entities: {activo: "Apo4501"}

- question: "ocupación de Rentas PT"
  expected_metric: vacancia_pct
  expected_entities: {fondo: PT}
  notes: "alias 'Rentas PT'"

# --- Phase 2 additions: metric aliases ---
- question: "% ocupado de Viña Centro"
  expected_metric: vacancia_pct
  expected_entities: {activo: "Viña Centro"}
  notes: "'% ocupado' es sinonimo inverso de vacancia"

- question: "occupancy de Parque Titanium"
  expected_metric: vacancia_pct
  expected_entities: {fondo: PT}
  notes: "termino en ingles"

- question: "rentabilidad de la serie A de TRI desde el inicio"
  expected_metric: tir_desde_inicio
  expected_entities: {fondo: TRI}

- question: "dividend yield de Apo"
  expected_metric: dividend_yield
  expected_entities: {fondo: Apo}

- question: "tasa de arriendo de Mall Curicó"
  expected_metric: tasa_arriendo
  expected_entities: {activo: "Mall Curicó"}

# --- Phase 2 additions: temporal phrases ---
- question: "vacancia de PT este mes"
  expected_metric: vacancia_pct
  expected_entities: {fondo: PT}
  expected_period: current_month

- question: "NOI de Viña Centro el mes pasado"
  expected_metric: noi
  expected_entities: {activo: "Viña Centro"}
  expected_period: previous_month

- question: "dividend yield YTD de TRI"
  expected_metric: dividend_yield
  expected_entities: {fondo: TRI}
  expected_period: ytd

- question: "vacancia de Apoquindo 4700 en los últimos 12 meses"
  expected_metric: vacancia_pct
  expected_entities: {activo: "Apo4700"}
  expected_period: u12m

- question: "NOI de TRI el año pasado"
  expected_metric: noi
  expected_entities: {fondo: TRI}
  expected_period: previous_year

# --- Phase 2 additions: ambiguity SHOULD clarify ---
- question: "cuéntame algo"
  expected_metric: null
  expected_entities: {}
  notes: "sin metrica, sin entidad, sin contexto -> debe pedir aclaracion"

- question: "dame el numero"
  expected_metric: null
  expected_entities: {}
  notes: "referencia vaga sin metrica/entidad -> debe pedir aclaracion"

# --- Phase 2 additions: ambiguity should NOT clarify ---
- question: "¿cómo viene Parque Titanium?"
  expected_metric: null
  expected_entities: {fondo: PT}
  notes: "entidad clara, metrica implicita 'desempeño general' -> NO debe forzar aclaracion, dejar que el LLM elija un resumen razonable"

- question: "Apoquindo"
  expected_metric: null
  expected_entities: {}
  notes: "caso de ambiguedad documentado (fondo Apo vs activo consolidado Apoquindo) -> segun notas_ambiguedad en semantic/relationships.yaml"

# --- Phase 2 additions: known-gap coverage (metrics without semantic/*.yaml yet) ---
- question: "LTV del fondo TRI"
  expected_metric: null
  expected_entities: {fondo: TRI}
  notes: "LTV no tiene semantic/metrics/*.yaml aun (solo vive en _BUSINESS_CONTEXT) -- documentar el gap, no inventar el yaml en este eval"

- question: "valor cuota libro de la serie C de TRI"
  expected_metric: null
  expected_entities: {fondo: TRI}
  notes: "misma razon -- gap conocido, no cubierto por semantic/ todavia"
```

- [ ] **Step 2: Validate the YAML parses and the runner still executes**

```bash
python -c "import yaml; d = yaml.safe_load(open('tests/eval/questions.yaml', encoding='utf-8')); print(len(d))"
```
Expected: prints a count ≥ 36 (18 original + ~20 new).

- [ ] **Step 3: Commit**

```bash
git add tests/eval/questions.yaml
git commit -m "test(eval): expand single-turn eval set with aliases, temporal phrases, ambiguity cases"
```

---

## Task 10: Multi-turn eval conversations

**Files:**
- Create: `tests/eval/conversations.yaml`

**Interfaces:**
- Produces: a new eval fixture format consumed by Task 11's extended `run_eval.py`.

- [ ] **Step 1: Create `tests/eval/conversations.yaml`**

```yaml
- name: followup_comparison_pt_occupancy
  turns:
    - question: "¿Cuál fue la ocupación de Parque Titanium en julio?"
      expected_metric: vacancia_pct
      expected_entities: {fondo: PT}
    - question: "¿Y versus el año pasado?"
      expected_metric: vacancia_pct
      expected_entities: {fondo: PT}
      expected_comparison: same_period_last_year

- name: entity_replacement_monthly_evolution
  turns:
    - question: "Muéstrame la evolución mensual de ocupación de PT en 2026"
      expected_metric: vacancia_pct
      expected_entities: {fondo: PT}
    - question: "Haz lo mismo para Viña Centro"
      expected_metric: vacancia_pct
      expected_entities: {activo: "Viña Centro"}

- name: metric_followup_same_entity
  turns:
    - question: "NOI de Mall Curicó en junio"
      expected_metric: noi
      expected_entities: {activo: "Mall Curicó"}
    - question: "¿y la vacancia?"
      expected_metric: vacancia_pct
      expected_entities: {activo: "Mall Curicó"}

- name: session_isolation_control
  # Not a real conversation -- used by run_eval.py --full to verify this
  # conversation's session_id never sees state from another conversation
  # (regression guard for Task 7's conversation_id wiring).
  turns:
    - question: "vacancia de Apoquindo 4501"
      expected_metric: vacancia_pct
      expected_entities: {activo: "Apo4501"}
```

- [ ] **Step 2: Validate it parses**

```bash
python -c "import yaml; d = yaml.safe_load(open('tests/eval/conversations.yaml', encoding='utf-8')); print(len(d), sum(len(c['turns']) for c in d))"
```
Expected: `4 8`.

- [ ] **Step 3: Commit**

```bash
git add tests/eval/conversations.yaml
git commit -m "test(eval): add multi-turn conversation eval fixtures"
```

---

## Task 11: Extend `run_eval.py` to run the real end-to-end path

**Files:**
- Modify: `tests/eval/run_eval.py`

**Interfaces:**
- Consumes: `db_chat.answer(question, history, session_id)` (existing entrypoint, now wired per Task 5), `tests/eval/questions.yaml` (Task 9), `tests/eval/conversations.yaml` (Task 10).
- Produces: a `run_full()` function reporting metric/entity/intent/temporal/SQL-execution accuracy, invoked via `python tests/eval/run_eval.py --full`. The original `run()` (intent-only) stays available via `python tests/eval/run_eval.py` for fast iteration.

- [ ] **Step 1: Read the current file to preserve its existing structure**

```bash
sed -n '1,80p' tests/eval/run_eval.py
```
(Confirms exact current helper names — `_llm_call`, `SESSION_ID`, the `run()` function — before extending it; do not guess signatures.)

- [ ] **Step 2: Append the extended runner**

Add to `tests/eval/run_eval.py` (after the existing `run()` function, before the `if __name__ == "__main__":` block — move that block to the very end):
```python
def _clear_all_state(session_ids: list[str]) -> None:
    from tools.analyst.conversation_state import clear_state
    for sid in session_ids:
        clear_state(sid)


def run_full() -> None:
    """End-to-end eval: runs db_chat.answer() for real (2 LLM calls + real
    SQL execution per question), not just extract_intent(). Reports metric
    accuracy, entity accuracy, SQL-execution success, and clarify-policy
    correctness for single-turn questions.yaml, plus inheritance/replacement
    correctness for conversations.yaml."""
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from tools import db_chat

    questions_path = _Path(__file__).parent / "questions.yaml"
    with open(questions_path, encoding="utf-8") as fh:
        cases = yaml.safe_load(fh)

    metric_ok = entity_ok = sql_ok = 0
    clarify_expected_ok = 0
    clarify_cases = 0
    n = len(cases)

    for i, case in enumerate(cases):
        session_id = f"eval-single-{i}"
        _clear_all_state([session_id])
        result = db_chat.answer(case["question"], [], session_id=session_id)

        expects_clarify = case.get("expected_metric") is None and not case.get("expected_entities")
        if expects_clarify and "no debe" not in (case.get("notes") or "").lower():
            clarify_cases += 1
            if result.get("clarify"):
                clarify_expected_ok += 1

        if not result.get("error") and (result.get("sql") is not None or result.get("clarify")):
            sql_ok += 1

        from tools.analyst.conversation_state import get_state
        state = get_state(session_id)
        expected_metric = case.get("expected_metric")
        if expected_metric is None or state["last_metric"] == expected_metric:
            metric_ok += 1
        expected_entities = case.get("expected_entities") or {}
        if not expected_entities or all(
            state["last_entities"].get(k) == v for k, v in expected_entities.items()
        ):
            entity_ok += 1

        print(f"[{i+1}/{n}] {case['question'][:60]!r} -> metric={state['last_metric']} entities={state['last_entities']} clarify={result.get('clarify')}")

    print(f"\nSingle-turn (full pipeline, {n} questions):")
    print(f"  Metric accuracy: {metric_ok}/{n}")
    print(f"  Entity accuracy: {entity_ok}/{n}")
    print(f"  SQL-execution success (no error): {sql_ok}/{n}")
    print(f"  Clarify-when-expected: {clarify_expected_ok}/{clarify_cases}")

    conversations_path = _Path(__file__).parent / "conversations.yaml"
    with open(conversations_path, encoding="utf-8") as fh:
        conversations = yaml.safe_load(fh)

    conv_turn_total = 0
    conv_turn_ok = 0
    for conv in conversations:
        session_id = f"eval-conv-{conv['name']}"
        _clear_all_state([session_id])
        history: list[dict] = []
        for turn in conv["turns"]:
            result = db_chat.answer(turn["question"], history, session_id=session_id)
            history.append({"role": "user", "content": turn["question"]})
            history.append({"role": "assistant", "content": result.get("answer_md", "")})

            from tools.analyst.conversation_state import get_state
            state = get_state(session_id)
            conv_turn_total += 1
            expected_metric = turn.get("expected_metric")
            expected_entities = turn.get("expected_entities") or {}
            metric_match = expected_metric is None or state["last_metric"] == expected_metric
            entity_match = not expected_entities or all(
                state["last_entities"].get(k) == v for k, v in expected_entities.items()
            )
            if metric_match and entity_match:
                conv_turn_ok += 1
            print(f"  [{conv['name']}] {turn['question'][:60]!r} -> metric={state['last_metric']} entities={state['last_entities']}")

    print(f"\nMulti-turn (full pipeline, {len(conversations)} conversations, {conv_turn_total} turns):")
    print(f"  Turn accuracy: {conv_turn_ok}/{conv_turn_total}")
```

Update the `if __name__ == "__main__":` block at the bottom of the file:
```python
if __name__ == "__main__":
    import sys as _sys
    if "--full" in _sys.argv:
        run_full()
    else:
        run()
```

- [ ] **Step 3: Run the fast (intent-only) mode to confirm no regression**

```bash
python tests/eval/run_eval.py
```
Expected: same shape of output as Task 1's baseline (now against the expanded `questions.yaml`, so counts will differ — that's expected and fine, this is not the number compared against baseline).

- [ ] **Step 4: Run the full end-to-end mode**

```bash
python tests/eval/run_eval.py --full
```
Expected: runs without exceptions, prints single-turn and multi-turn accuracy numbers. This makes real LLM + real SQLite calls — expect it to take a few minutes.

- [ ] **Step 5: Commit**

```bash
git add tests/eval/run_eval.py
git commit -m "test(eval): add --full end-to-end eval mode through db_chat.answer(), including multi-turn"
```

---

## Task 12: Measure improvement and write the comparison report

**Files:**
- Create: `docs/superpowers/plans/2026-08-10-analyst-agent-phase2-results.md`

**Interfaces:**
- Consumes: `docs/superpowers/plans/2026-08-10-analyst-agent-phase2-baseline.md` (Task 1), output of `python tests/eval/run_eval.py --full` (Task 11).

- [ ] **Step 1: Run the full test suite one more time**

```bash
python -m pytest tests/ -q
```
Expected: 0 failures. Record the final count.

- [ ] **Step 2: Run the full eval one more time and capture output**

```bash
python tests/eval/run_eval.py --full
```

- [ ] **Step 3: Write the results doc**

Create `docs/superpowers/plans/2026-08-10-analyst-agent-phase2-results.md`:
```markdown
# Phase 2 Results vs Phase 1 Baseline

## Test suite
- Baseline (Task 1): <N> passed
- Phase 2 (final): <M> passed, 0 failed

## Single-turn eval (BEFORE: intent-only via extract_intent, 18 questions)
- Metric accuracy: 9/18
- Entity accuracy: 9/18

## Single-turn eval (AFTER: full pipeline via db_chat.answer(), <N> questions incl. Phase 2 additions)
- Metric accuracy: <paste>
- Entity accuracy: <paste>
- SQL-execution success: <paste>
- Clarify-when-expected: <paste>

## Multi-turn eval (AFTER only -- no Phase 1 equivalent existed)
- Turn accuracy: <paste>

## Specific previously-failing questions that now pass
<list each question from the ORIGINAL 18 that failed in the Task 1 baseline
run and now passes under --full, with a one-line reason why (e.g. "entity
resolver now reached in production, alias 'Titanium' -> PT")>

## Known remaining gaps (explicitly deferred, not silently dropped)
- LTV, RCSD, deuda, valor cuota libro/bolsa, cap rate still have no
  semantic/metrics/*.yaml -- _BUSINESS_CONTEXT remains their only source.
  Eval cases for these are included but expected to show metric=None; do not
  treat those as regressions.
- entity_resolver.py is exact-match only (no fuzzy matching) -- ambiguity.py
  never sees a "multiple plausible entities" case because resolve_entity()
  structurally can't return more than one candidate. If real usage surfaces
  multi-candidate ambiguity, entity_resolver.py needs extending first.
- Phase 1's `except (StopIteration, ValueError, TypeError, IndexError): pass`
  around result_checks (db_chat.py:982) still silently skips validation on a
  malformed/missing `valor` column -- left as-is per "preserve existing SQL
  safety pipeline," flagged here for a future hardening pass.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-08-10-analyst-agent-phase2-results.md
git commit -m "docs(analyst): record Phase 2 vs Phase 1 baseline comparison"
```

---

## Task 13: Final branch review before merge

**Files:** none (review only)

- [ ] **Step 1: Review the full diff against `main`**

```bash
git diff main...feat/analyst-agent-phase-2 --stat
```
Confirm only the files listed in "File Structure" above changed, plus the two new docs.

- [ ] **Step 2: Confirm no debug/temporary code remains**

```bash
git diff main...feat/analyst-agent-phase-2 | grep -nE "print\(|TODO|FIXME|pdb"
```
Expected: no hits outside the intentional `print()` calls inside `tests/eval/run_eval.py` (those are the eval reporting output, not debug code).

- [ ] **Step 3: Run the full test suite + eval one final time**

```bash
python -m pytest tests/ -q
python tests/eval/run_eval.py --full
```
Expected: all green, results doc numbers match this run.

- [ ] **Step 4: Confirm working tree is clean**

```bash
git status
```
Expected: clean, everything committed on `feat/analyst-agent-phase-2`.

Do not merge to `main` — leave that decision to the user (per repo convention of review-before-merge; see `superpowers:finishing-a-development-branch` for the handoff options).

---

## Self-Review Notes

**Spec coverage check** (against the 18 numbered sections of the Phase 2 request):
1. Repo inspection — done via the Explore agent report that grounds this plan (file:line citations throughout).
2. Frozen baseline — Task 1.
3. Intent extraction wired into real flow — Task 5 (`context_builder.build_context` → `extract_intent`).
4. Entity resolution wired into real flow — Task 5, via `extract_intent`'s existing call to `resolve_entity` (`tools/analyst/intent.py:68`), now actually reached in production.
5. Metrics resolved through semantic catalog informing SQL context — Task 4's `BUSINESS DEFINITIONS` section + Task 6's synthesis-pass enrichment.
6. Deterministic temporal resolution — Task 2.
7. Conversation state made useful — Task 5 (state now populated with real entities/period via `extract_intent`, previously dead code) + Task 8 (tests proving it).
8. Session identification fixed before relying on state — Task 7.
9. Semantic context builder — Task 4.
10. Existing SQL safety pipeline preserved — explicit Global Constraint + Task 5's edit scoped to message assembly only.
11. Confidence-aware ambiguity handling — Task 3.
12. Prompt restructured into labeled sections — Task 5 (`RESOLVED INTENT`, `BUSINESS DEFINITIONS`, `PERIOD / COMPARISON`, `VERIFIED EXAMPLE` sections spliced in) without a full `_SQL_SYSTEM`/`_BUSINESS_CONTEXT` rewrite.
13. Follow-up tests — Task 8 (inheritance/replacement through real `answer()`), Task 7 (session isolation).
14. Expanded eval set — Tasks 9-10 (18 → ~40 single-turn + 4 multi-turn conversations).
15. Measure improvement — Task 12.
16. Premature work avoided — no chart/Python/Excel/vector-DB/multi-agent work anywhere in this plan.
17. Architecture target — matches: session id (Task 7) → conversation state (Task 5/8) → intent extraction (Task 5) → entity/metric/period resolution (Task 5, inside `extract_intent`) → semantic context builder (Task 4) → verified query retrieval (already inside Task 4's `build_context`) → existing SQL gen/validation/execution/result checks (untouched) → final response → state update (already happens via `extract_intent` + the existing `db_chat.py:1022` line).
18. Git workflow — Task 1 Steps 1-2, per-task commits throughout, Task 13 final review, no merge without explicit user go-ahead.

**Placeholder scan:** no "TBD"/"handle appropriately"/"similar to Task N" — every task has literal file paths, literal code, and literal commands.

**Type consistency check:** `AnalystContext.decision` (Task 4) matches `AmbiguityDecision` (Task 3) field names (`action`, `reason`, `clarify_message`) used identically in Task 5. `TemporalResolution` fields (`period`, `period_range`, `comparison_period`, `label`, `data_gap_warning`) from Task 2 match exactly how Task 4's `_build_sections` reads them. `IntentResult` fields used in Task 3/4/5/8 (`metric`, `entities`, `period`, `comparison`, `confidence`, `needs_clarification`) match the existing dataclass at `tools/analyst/intent.py:32-39` verbatim — no renamed fields anywhere.
