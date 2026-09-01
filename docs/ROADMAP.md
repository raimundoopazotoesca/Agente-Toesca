# Roadmap — Toesca Real Estate AI Analyst

This is the live roadmap. For what's actually true right now, see `docs/CURRENT_STATE.md`
— this file states sequence and intent, not verified present-tense fact. If this file and
`docs/CURRENT_STATE.md` disagree about whether something is done, `CURRENT_STATE.md` wins.

**Historical predecessor**: the previous `ROADMAP.md` (root, "v2.1", 2026-07-24) is
preserved at `docs/archive/ROADMAP-v2.1-2026-07-24.md`. It documents Phases 0–4 of an
earlier "Financial Intelligence Platform" plan and remains valuable as a record of closed
work (data-foundation hardening, Streamlit-cluster removal, server auth, schema
re-baselining) — but it describes an Analyst architecture (`web/chat_bubble.js` +
`tools/db_chat.py`) that predates `tools/analyst_runtime/` and should not be read as
current. See `docs/CURRENT_STATE.md`'s Product table for what actually exists today.

## Sequence (approved)

```
A0 — [closed] Data foundation hardening (the old ROADMAP.md's Phase 0/1)
A1 — [closed] JLL v2 governed ingestion pipeline, implemented + tested in source (this commit, d986996)
A1.5 — [closed] Documentation base alignment (Pass 1.5 — fast-forwarded this branch onto A1's work)
     ↓
Eval Foundation Step 0                              [closure in progress, parallel Track A]
     ↓
Documentation Reset / Current State Sync             ← this branch, docs/current-state-reset
     ↓
Baseline Debt Triage / Burn-down #1
     ↓
A2 — Agent Architecture
     ↓
A3 — Tools, SQL & Safety
     ↓
Product Shell & Reporting v1
     ↓
A4 — Context & Conversation
     ↓
A5 — Evals & Observability
     ↓
A6 — Roadmap & Development Process
     ↓
External data / Inciti / personalized artifacts / Excel / PPT / etc.
```

### Closed blocks (historical record, not operational state)

- **A0 — Data foundation hardening.** Corresponds to the old ROADMAP.md's Phase 0:
  DB integrity (Apoquindo key consolidation, migration 058; referential integrity to
  zero; partial-unique indexes), server auth (`X-Ingesta-Token`), Streamlit-cluster
  removal, repo hygiene, schema re-baselining. Full detail: `docs/archive/ROADMAP-v2.1-2026-07-24.md`.
  Do not treat any specific number in that archived file (schema_version, row counts) as
  current — check `docs/CURRENT_STATE.md` instead.
- **A1 — JLL v2 governed ingestion pipeline.** Migrations 085–091, ingestion/derivation
  code, 70 new tests, wired into the live ingesta web UI. Implemented and tested in
  source; gated off production. Full detail in `docs/CURRENT_STATE.md`'s JLL v2 section —
  intentionally not re-summarized here to avoid a second copy that can drift.
- **A1.5 — Documentation base alignment.** This branch was fast-forwarded from
  `origin/feat/alpha-v0.1` (`c819e87d`) onto `d986996ba` specifically so the documentation
  reset in progress here would reflect A1's work rather than a stale pre-JLL-v2 snapshot.

### Eval Foundation Step 0 (in progress, parallel track)

Owned by Track A, branch `audit/analyst-eval-blueprint-v1` (PR #1). This documentation
branch does not read from or depend on that branch's working tree. Its closure/final
required-check state will be synchronized into `docs/CURRENT_STATE.md` once Track A
reports it — no PASS/FAIL is assumed here, and no future SHA is invented.

### Documentation Reset / Current State Sync (this work)

Establishes `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md` as
canonical sources and aligns `README.md`/`AGENTS.md`/`CLAUDE.md`/`CODEX.md` to point at
them instead of duplicating state. See `docs/CURRENT_STATE.md` for exactly what's real
right now; this roadmap file states what comes next.

### Baseline Debt Triage / Burn-down #1

Not yet started. Will consume `docs/CURRENT_STATE.md`'s "Known debt / blockers" section
as its starting inventory — technical debt, architectural debt, and open business
decisions are already separated there so this triage doesn't have to re-derive that split.

### A2 — Agent Architecture

Not yet started as a formally scoped block, but **not greenfield either**: per the Pass
1.5 delta audit, `tools/analyst_runtime/canonical_guard.py`, `coverage_guard.py`, and
`sqlite_guard.py` already exist and are in active use. This block should audit what's
already built against what the old ROADMAP.md's Phase 2 items (F2.0 contract
documentation, F2.2 traceability/`chat_query_log`, F2.3 SQL-allowlist validation) actually
require, rather than treating those items as 0% done.

### A3 — Tools, SQL & Safety

Depends on A2's findings. Likely scope: closing whatever gap A2 finds between
`sqlite_guard.py`'s actual behavior and the SQL-allowlist validation the old roadmap
specified (AST-based, e.g. `sqlglot`); resolving the `db_chat.py`/`analyst_runtime`
relationship flagged as open debt in `docs/CURRENT_STATE.md`.

### Product Shell & Reporting v1

**Approved target — not yet implemented.** Two parts:

**Assistant-first UX.** The Analyst becomes the primary application/workspace, not the
factsheet.

- `/analyst` as the primary entry point.
- Primary navigation lives in the Analyst.
- Factsheet becomes a capability reachable *from* the Analyst, not a separate portal.
- Conversations, reports, and future artifacts are all accessed from inside the Analyst.

Per `docs/CURRENT_STATE.md`: recent commits (product rename to "Toesca Real Estate AI
Analyst," login/loading redesign) already treat the Analyst as the primary UX investment.
Nothing today wires navigation *from* the Analyst *to* the factsheet — that link is new
work, not something to discover as already done.

**Reports Hub.** Deterministic HTML artifacts, generalizing the pattern
`scripts/build_factsheet.py` already established — not a new invention:

```
button / Analyst tool
        ↓
deterministic report generator
        ↓
governed dataset / SQL
        ↓
validation
        ↓
HTML template
        ↓
report
```

- **No LLM, no model API** in the report-generation path. Governed SQL/datasets → code →
  HTML. Reproducible, testable.
- Same governed semantic/data contract as the Analyst (`semantic/`, `tools/datasets/`) —
  **not a second metrics implementation.**
- The future Analyst can invoke the *same* generator, e.g.
  `generate_vacancy_report(scope="TRI", period="2026-07")` — not a separate LLM-driven
  path that reimplements the same numbers.

Three named reports, with current data-layer feasibility per `docs/CURRENT_STATE.md`:

| Report | Data-layer precedent | Open blocker |
|---|---|---|
| **Informe de Vacancia** | `v_vacancia_activo_tipo` exists; migration 090 makes `UG` visible as its own category | UG's rentable-vs-excluded treatment is an open business decision, not a data gap |
| **Informe de Recaudación** | `raw_cartera_line` (aging buckets) and `raw_recaudacion` (JLL v2, migration 086) are lineage-complete and provider-agnostic by design | A `tasa_recaudacion` KPI is deliberately not derivable yet — no invoice/document linkage exists to make it a real cohort rate; do not define it until business approves the contract |
| **Informe de Ingresos** | `raw_movimiento_contable_line` (086) plus `derive_er_jll_v2.py` give more granular, lineage-tracked income/expense lines, but they flow into the existing `raw_er_activo_line`, not a new surface | Less advanced than the other two — this is a data-quality improvement to an existing report path, not a new capability |

Extensible to future reports once this pattern is proven on the three above.

### A4 — Context & Conversation

Not yet started.

### A5 — Evals & Observability

Not yet started. Will build on what's already present per `docs/CURRENT_STATE.md`'s Eval
& Observability section (`eval/benchmark/`, `eval/product_alpha/`, `eval/round_b/`) rather
than starting from zero.

### A6 — Roadmap & Development Process

Not yet started.

### External data / Inciti / personalized artifacts / Excel / PPT / etc.

Not yet started. Deferred by design until the blocks above are in place.
