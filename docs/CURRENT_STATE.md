# Toesca Real Estate AI Analyst — Current State

**This is the canonical source for "what exists right now."** If any other document
(`README.md`, `AGENTS.md`, `CLAUDE.md`, `CODEX.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`,
`wiki/`) states a current fact that contradicts this file, treat this file as correct
and flag the other one for correction — per `AGENTS.md`'s evidence-authority order
(code → migrations/schema → tests → CI → git → docs marked current → old narrative docs).

Do not hand-copy this file's content into another doc. Other docs should **link here**
for state and keep only their own subject matter (rules, roadmap, architecture).

## Snapshot

| Field | Value |
|---|---|
| Canonical protected branch | `feat/alpha-v0.1` |
| Protected base HEAD captured for this checkpoint | `58cb06bc832e35a01a713d22219e6947853c03ff` (merge commit of PR #23, "feat/a3-3-factual-trend-validation" — closes A3.3) |
| Checkpoint documentation source commit | `c760086c70a1e0811f6d75762fef0402cf24a9f7` (historical — source commit for the prior, 2026-09-03 checkpoint; A3.1/A3.2/A3.3 all landed after that checkpoint without a doc sync, closed by this update) |
| Date verified | 2026-09-11 |
| Latest migration in repo (on this branch's own tree) | `091_rent_roll_semantic_renta.sql` (`tools/db/migrations/`) — unchanged since the prior checkpoint |
| Production DB schema (last known, per source-level self-disclosure — not independently checked against a live DB) | `84` — migrations 085–091 are **not yet applied to production** (unchanged; not re-verified against a live DB as part of this sync) |
| Test files in repo | 165 under `tests/`, 63 `.py` files under `eval/` (27 `test_*.py`) (file counts, not a pass/fail run) |
| **Eval Foundation Step 0** | **CLOSED / PASS.** PR #1 ("eval: make analyst evaluation foundation load-bearing") merged into the protected branch `feat/alpha-v0.1`. See "Eval Foundation Step 0" under Eval & Observability below for the full gate detail. |
| **Documentation Reset / Current State Sync** | **CLOSED / PASS.** PR #2 merged. |
| **Pilot Quality Standard v1** | **CLOSED / PASS.** PR #3 merged; canonical files: `docs/pilot/PILOT_QUALITY_STANDARD_V1.md`, `docs/pilot/PILOT_EVAL_MATRIX_V1.md`, and `docs/pilot/PILOT_TASK_BANK_V0.md`. |
| **Baseline Debt Burn-down #1** | **CLOSED / PASS.** PR #5 merged. Historical allowlist: 19 → 14. |
| **A2 — Agent Architecture** | **CLOSED / PASS.** PR #6 merged. Established the canonical single-Analyst architecture; `tools/db_chat.py` / `POST /api/chat` confirmed transition-only (see `docs/a2-db-chat-transition-boundary.md`). |
| **Baseline Debt Burn-down #2** | **CLOSED / PASS.** PR #7 merged. Historical allowlist: 14 → 0. `eval/baselines/pytest-known-failures.json` now holds an empty `failure_ids` list (verified directly at this HEAD). Overall trajectory: 19 → 14 → 0. |
| **A3.1 — SQL Safety** | **CLOSED / PASS.** Sub-slices A3.1a–A3.1e all merged: PR #9 (governed SQL surface registry, `feat/a3-1a-sql-surface`), PR #11 (SQLite authorizer, `feat/a3-1b-sqlite-authorizer`), PR #13 (per-statement timeout, `feat/a3-1c-sql-timeout`), PR #14 (structural validation, `feat/a3-1d-sql-structural-validation`) + PR #15 (trailing-semicolon fix, `fix/a3-1d-trailing-semicolon`), PR #16 (full-stack adversarial gate, `feat/a3-1e-sql-safety-stack-gate-resume`). PRs #10 and #12, interleaved in the same merge sequence, are unrelated UI fixes, not A3.1 sub-slices. See `tools/analyst_runtime/sqlite_guard.py` and `tools/db/sql_surface.py`. |
| **A3.2 — Result + Evidence Contract** | **CLOSED / PASS.** Sub-slices A3.2a–A3.2f all merged (PRs #17–#22): `ToolResult`/`ToolEvidence` Result-Evidence contract, governed-dataset producers bounded via `row_limit`, `controlled_sql` transported as supporting/non-canonical evidence (never promoted to a canonical claim), synthesis evidence-ref hardening, durable evidence projection for restart hydration, and E2E lifecycle hardening. `canonical_guard.py` (Stage 5.3) is now formally deprecated — not production-wired, retained only as `coverage_guard.py`'s single-fact parity reference. (Name per `docs/ROADMAP.md`'s official A3.2 label; the sub-slice sequencing itself is a reasonable execution-time refinement not reflected in the roadmap's single-slice description.) |
| **A3.3 — Result Validation** | **CLOSED / PASS.** PR #23 merged (merge commit `58cb06bc832e35a01a713d22219e6947853c03ff`, same commit as the protected HEAD row above; implementation commit `6af793b`, "deterministic trend-direction validation over A3.2 claims" — not itself a merge commit). Adds `tools/analyst_runtime/trend_assertions.py` and coverage-guard integration that fail-closed on UP/DOWN/FLAT drift against governed evidence. **Do not modify this implementation as part of documentation work** — it is closed and out of scope for this sync. (Name per `docs/ROADMAP.md:169`. PR #24, `fix/pilot-export-feedback-test`, merged immediately after PR #23 in the same sequence — unrelated UI/test fix, not part of A3.3.) |
| Current development phase | A0/A1/A1.5, Eval Foundation Step 0, Documentation Reset, Pilot Quality Standard v1, both Baseline Debt Burn-downs, A2 — Agent Architecture, and now **all of A3.1, A3.2, and A3.3 are closed.** JLL v2 remains a separate parallel track — technical cutover candidate frozen, external gate pending (unchanged by this checkpoint). **No phase is assumed to be "next" by default.** A3.4 (Trace / Retention / Auditability) and A4 (advanced intelligence) both remain future work per `docs/ROADMAP.md`, but this checkpoint deliberately does not commit to either as the immediate next slice — the post-A3.3 conversational benchmark surfaced gaps (deixis/conversation state, synthesis completeness, retrieval-vs-missing-data ambiguity, entity-set references) that are not yet reproduced with trace evidence. See `docs/A3_POST_A3.3_GAP_REGISTER.md` for the gap-by-gap classification and what would need to happen before any of them becomes implementation scope. |

<!-- AUTO-GENERATED:START -->
Not implemented. No `scripts/update_current_state.py` exists yet. The fields above
were verified by hand on the date stated. See "Auto-update design" at the bottom
of this file for which fields would be safe to generate mechanically if that script
is ever written, and which must stay hand-authored regardless.
<!-- AUTO-GENERATED:END -->

## Product — what exists today

One Flask process, `scripts/ingesta_server.py`, serves every surface below on
`127.0.0.1:8765` (or wherever deployed). There is no separate frontend server.

| Surface | Entry point | Status |
|---|---|---|
| **Toesca Real Estate AI Analyst** (chat/workspace) | `/analyst`, `web/analyst.html` + `web/analyst_workspace.js`, backed by `tools/analyst_runtime/` (reasoning loop) + `tools/analyst_workspace/` (conversation persistence) + `tools/analyst_api.py` (HTTP adapter) | **Primary product, active development.** This is the newest and most actively developed surface — recent commits rename the product to "Toesca Real Estate AI Analyst," redesign login/loading, and add a pilot-feedback loop. |
| Ingesta web (validated data upload) | `/ingesta`, `web/ingesta.html` | Active. 6-tab wizard: check → validate → preview → commit, human-confirmed. Now also auto-detects and handles JLL v2 format uploads (see JLL v2 section below). |
| Factsheet (HTML) | `/factsheet`, generated by `scripts/build_factsheet.py` | Active, canonical per `docs/ROADMAP.md` F1.4. 100% SQL-driven, no LLM in its generation path. **Target state (approved, not yet built): reachable as a capability from inside the Analyst, not the primary entry point** — see "Product Shell & Reporting v1" in `docs/ROADMAP.md`. |
| Pilot feedback / control | `/pilot-feedback`, `/pilot-control` | Active. Recent additions (message feedback, product-update surfacing, feedback-report markdown export) — this is real, shipped surface, not a design doc. |
| Login / auth | `/login`, `/api/auth/*` | Active. Session-based; recently redesigned. |
| Old chat bubble (`web/chat_bubble.js`, `tools/db_chat.py`, `POST /api/chat`) | still present on disk and still routed | **Prior-generation, transition-only.** This predates `tools/analyst_runtime/`. A2 (PR #6, closed) formally established the canonical single-Analyst architecture and confirmed `db_chat.py`/`POST /api/chat`'s caller/capability scope — see `docs/a2-db-chat-transition-boundary.md` and "Known debt / blockers" below. The canonical runtime does not and must not import it (regression-guarded). Retirement itself is still not met — do not assume it is dead code without checking `scripts/ingesta_server.py`'s `/api/chat` route and its callers first. |
| `agent.py` (legacy, 102-tool Gemini agent for Outlook/SharePoint/Excel) | CLI / `--server` | **Legacy.** Still the only interface for Outlook/Excel/SharePoint automation tasks (see `AGENTS.md`/`CODEX.md` for that surface's operational rules — those still apply, they describe a still-real, still-used tool). Its long-term role is an open roadmap question (`docs/ROADMAP.md` §8.3 in the archived `ROADMAP.md` — not yet re-decided in the current roadmap). |
| Factsheet PPTX (`tools/factsheet_tools.py`, 1,326 lines) | 14 tools in `agent.py`'s registry | **Legacy, scheduled for controlled removal.** Do not extend. Not yet removed as of this SHA. |

## Data Foundation

**Database**: `memory/agente_toesca_v2.db` (SQLite). This is the single business-data
source of truth — see `AGENTS.md` for the non-negotiable rules around it (never
`memory/agente_toesca.db`, never touch `superseded_at`-filtered rows without the filter,
etc.).

**Canonical/raw surfaces**: `dim_*` master catalogs, `raw_*_line` (one row per source
document line, full lineage), `raw_*` snapshot/event tables, `fact_*` derived facts,
`derived_kpi` (KPI cache). Full table-by-table description lives in `docs/ARCHITECTURE.md`
— not duplicated here.

**Semantic / governance layer**: `semantic/` (`domains.yaml`, `entities.yaml`, `metrics/`,
`relationships.yaml`, `schema/`, `synonyms.yaml`) and `tools/datasets/` (`catalog.py`,
`catalog_v1.yaml`, `executor.py`, `models.py`) define the governed dataset contract that
both the Analyst and deterministic report generators are meant to share (see "Product
Shell & Reporting v1" in `docs/ROADMAP.md` — this sharing is the whole point of that
design, not yet built).

**Known semantic debt**:
- `tools/datasets/catalog_v1.yaml:59` still declares `rent_rate_uf_m2: {field: renta_uf, ...}`
  — the pre-JLL-v2-cutover definition. `docs/rent-roll-renta-semantics-v1.md` documents
  precisely why this is *currently correct but intentionally not yet updated* to match
  migration 091's `v_rent_roll_semantic` (three separate fields instead of one overloaded
  `renta_uf`). The catalog update is meant to ship in the same change as the production
  migration apply — **do not update the catalog ahead of that cutover.**
- Entity resolution for JLL v2 is a hardcoded dict (`_FAMILIA` in
  `tools/db/ingest_jll_planilla.py:78-82`), not a general resolver. Fine for its current
  scope; don't assume it generalizes to other providers without checking.
- Config for fondos is still duplicated across `FONDOS_CFG`, `NOI_ACTIVOS`/`RR_ACTIVOS`,
  `SHEET_CFG`, `SERIES_CONFIG` (legacy `agent.py`-era code) despite `dim_fondo`/`dim_serie`
  existing as the canonical source. Not yet consolidated.

## JLL v2

**This section is deliberately not compressed to "done" or "not started." Three
independent claims, each separately verified:**

### Implemented and tested (in source, at this SHA)

Migrations `085`–`091` are present in `tools/db/migrations/` — `091` is the highest
migration number in the repo. They add:

- **085**: typed renta semantics + provenance columns on `raw_rent_roll_line`
  (`renta_semantica` enum, `renta_uf_m2`, `fuente_proveedor`, `fuente_formato`). No
  backfill in this migration — deferred to 089, deliberately.
- **086**: three new governed tables, provider-agnostic by design —
  `raw_movimiento_contable_line`, `raw_cartera_line` (aging buckets: 1-30/31-60/61-90/91+
  days, `saldo_por_vencer`, `total_cartera`), `raw_recaudacion` (collections by
  activo/período).
- **087**: `dim_er_regla_interna` — versioned internal ER rules (contribuciones, seguros
  that JLL doesn't provide), data-only parameters, immutable-version semantics. Seeded
  with 7 real rows justified by a year-by-year deviation analysis in the migration
  comment.
- **088**: ER lineage — `origen`/`origen_regla_id` on `raw_er_activo_line` plus a bridge
  table `raw_er_movimiento_lineage`, with SQLite trigger-enforced coherence (a documented
  workaround for SQLite's lack of `ADD CONSTRAINT`).
- **089**: deterministic, idempotent backfill of `fuente_proveedor`/`fuente_formato` by
  filename pattern. Classification-only — no financial values altered. Unmatched rows get
  an explicit `'legacy_unknown'` sentinel rather than a guess.
- **090**: `UG` becomes its own vacancy category in `v_vacancia_activo_tipo` instead of
  silently falling into `'Otro'` — makes an open business decision (is UG rentable GLA?)
  *visible*, does not resolve it.
- **091**: rebuilds `v_rent_roll_semantic` into three explicit fields (`renta_semantica`,
  `renta_total_uf`, `renta_uf_m2`) instead of one overloaded `renta_uf` (kept for backward
  compatibility, flagged "desaconsejado").

Supporting code: `tools/jll_planilla_tools.py` (parser), `tools/db/ingest_jll_planilla.py`
(460-line validate/commit orchestrator, fail-loud on blocking anomalies, hash-based
crash-safe retry), `tools/db/derive_er_jll_v2.py` (348-line ER derivation with fail-closed
precedence — never silently overrides an internally-authoritative account), `tools/db/er_reglas.py`,
`tools/db/repo_jll_v2.py`, `tools/db/repo_rent_roll.py`.

Tests: 70 new test functions across three new files (`tests/db/test_ingest_jll_planilla.py`,
`tests/db/test_er_reglas_internas.py`, `tests/test_ingesta_server_jll_v2.py`), plus 4 new
schema invariants, plus two existing tests (`tests/db/test_baseline.py`,
`tests/analytics/test_vacancy_segmentation.py`) explicitly reworked to account for
production being behind head rather than assuming it's current.

The upload path is wired into the live ingesta web UI with automatic format detection —
**not CLI-only.**

### Production disposition

Production remains on schema `84`, per the commit's own message and `wiki/log.md`'s
entry ("Implementado en sandbox. NO aplicado a producción."). **085–091 are not applied
to production.** Re-ingestion is blocked by an explicit gate pending the official JLL
file. Whether that gate has since been passed cannot be determined from source alone —
this is a deployment-state fact, not a code-state fact, and this document does not assert
it either way. A separate branch, `feat/jll-v2-production-readiness` (not merged into
this branch), carries 12 further commits of SHA/tag preflight gating, E2E tests, and
cutover runbooks — i.e., a distinct, later-stage readiness effort exists and is not yet
part of this branch's history.

### Analyst availability

Zero code changes in `tools/analyst_runtime/` or `web/analyst.html` are associated with
this pipeline (confirmed via `git diff` across the delta). **The Analyst cannot query any
of the new JLL v2 tables or views today.** The data is populated (in sandbox) but not
Analyst-queryable — this is a "not wired up yet" state, not a bug in either component.

## Analyst

**Runtime**: `tools/analyst_runtime/` — a provider-neutral reasoning loop
(`analyst_loop.py`) plus a wire-protocol adapter layer (`transport.py`), explicitly
designed so the reasoning policy never imports a specific provider SDK. Companion
modules: `coverage_guard.py` (the single active claim validator; claims must be backed
by governed data with explicit coverage checks), `derived_claims.py`, `evidence_inventory.py`,
`live_sandbox.py`, `sqlite_guard.py`, `synthesis_schema.py`, `presentation.py`, `resolution.py`,
`session.py`. `canonical_guard.py` (Stage 5.3)
is DEPRECATED as of A3.2f: not production-wired, retained only as `coverage_guard.py`'s
single-fact parity reference (see its module docstring).

**A3.2 (closed)** added the Result/Evidence contract end to end: `ToolResult`/`ToolEvidence`
bound model-visible rows via `row_limit`, `controlled_sql` (free/long-tail SQL) is transported
as supporting/non-canonical evidence and never promotes to a canonical claim, synthesis carries
explicit evidence refs, and evidence now projects durably for restart hydration
(`tests/analyst_workspace/test_a3_2e_durable_evidence_restart.py`).

**A3.3 (closed)** added `trend_assertions.py` and `turn_trace.py`: deterministic validation of
trend direction (UP/DOWN/FLAT) over A3.2 claims, fail-closed on semantic drift, plus a
per-turn trace record. This is a narrower, closed-scope companion to `coverage_guard.py`
(numeric claims) — it does not itself constitute the broader trace/auditability work scoped
for A3.4.

**Persistence**: `tools/analyst_workspace/` — `conversation_service.py`, `store.py`,
`admin.py`, `export_markdown.py`, `title_generator.py`. This is a separate concern from
the reasoning loop: conversations, feedback, and workspace state.

**HTTP adapter**: `tools/analyst_api.py` — deliberately does not import or construct the
service directly; the Flask app supplies it via a lazy factory so HTTP tests and module
imports stay free of workspace/provider/DB side effects.

**Current strengths**: claim-level guards (`coverage_guard.py`; `canonical_guard.py` is
deprecated, see above) that appear more sophisticated than the regex-based mutation gate
the old `agent.py` uses —
**not independently verified by reading `sqlite_guard.py` line-by-line in this audit
pass; verify before relying on this claim for a safety-critical decision.**

**Current architectural debt**:
- Relationship to the old `db_chat.py`/`chat_bubble.js` chat surface is unresolved (see
  Product table above).
- No entity-resolution component beyond the JLL v2 module's hardcoded dict — the Analyst's
  own entity resolution (fondo/activo/serie key handling) has known ambiguity issues
  documented in `docs/matriz-claves-ambiguas-apoquindo.md`.
- Governed analytics (via `tools/datasets/`, `semantic/`) vs. long-tail free SQL: both
  paths exist; which questions route to which, and how consistently, was not verified in
  this audit pass.

## Eval & Observability

Present in the repo (spot-checked at this checkpoint's protected HEAD,
`58cb06bc832e35a01a713d22219e6947853c03ff`; Eval Foundation Step 0 was originally
established by PR #1, merge commit `631987393f240a17d902bf5a61104119c0e3eb98` — a prior
revision of this section mislabeled this as "PR #1's protected base `4d0a13075736c9bfd5f7c420c684253a636cd093`", but that SHA is actually the merge commit of PR #3
("Pilot Quality Standard v1"), unrelated to PR #1; corrected here):
- `eval/benchmark/` — frozen dev/holdout process (`DEV_SET_V1_FREEZE.md`,
  `HOLDOUT_SET_V1_FREEZE.md`, `PENDING.md` — known gaps include unvalidated
  `renta_uf/m²`, no capex, no morosidad table, unvalidated DSCR).
- `eval/product_alpha/` — a separate, newer eval track (`cases.py`, `grader.py`,
  `models.py`).
- `eval/round_b/` — a mini-dev/screening track (`mini_dev_v1.yaml`, `runner.py`,
  `composite.py`, `incremental.py`, `build_screening_8.py`); the file set here has
  changed since this section was first written — treat individual filenames as
  illustrative, not a verified inventory, and re-check before citing one.
- `eval/analysis/audit_renta_uf_semantics.py` — the reproducibility script backing
  `docs/rent-roll-renta-semantics-v1.md`'s claims.

**Eval Foundation Step 0: CLOSED / PASS.** Track A (`audit/analyst-eval-blueprint-v1`)
merged as PR #1 ("eval: make analyst evaluation foundation load-bearing") into the
protected branch `feat/alpha-v0.1`, merge commit `631987393f240a17d902bf5a61104119c0e3eb98`
(see the correction note above this section — `4d0a13075736c9bfd5f7c420c684253a636cd093`,
previously cited here, is PR #3's merge commit, not PR #1's).

**Required checks, active on `feat/alpha-v0.1`** (GitHub ruleset "Toesca protected devel";
target: `feat/alpha-v0.1` only; enforcement: active; bypass: none; strict/up-to-date
requirement: **off**):
- `tests (baseline-gated)`
- `eval/benchmark/tests (must be 100% green)`
- `eval/product_alpha/tests (must be 100% green)`

**Baseline-aware CI behavior**: the `tests (baseline-gated)` check does not require a
zero-failure suite — it requires the failure set to match an explicit, tracked allowlist.
At Eval Foundation Step 0's original closure (historical, PR #1): **19 historical allowed
failures** (pre-existing, tracked debt — not a regression), and every other gate bucket
empty: `new_failure_ids = []`, `new_anomalous_ids = {}`, `stale_pass_ids = []`,
`prohibited_state_ids = {}`, `not_collected_ids = []`, `collection_errors = []`,
`internal_errors = []`. `eval/benchmark/tests` and `eval/product_alpha/tests` must both be
100% green with no allowlist.

**Current state, as of this checkpoint (protected HEAD `58cb06b`; unchanged since the
prior `c760086` checkpoint — re-verified, not re-derived)**: the historical
allowlist has been fully burned down — 19 → 14 (Burn-down #1, PR #5) → 0 (Burn-down #2,
PR #7). `eval/baselines/pytest-known-failures.json` now contains an empty `failure_ids`
list at this HEAD (verified directly). Any new test failure now trips the gate as a
regression — there is no remaining historical allowance. PR #7's final CI ran green
(`tests (baseline-gated)`, `eval/benchmark/tests`, `eval/product_alpha/tests` all
passing) after a rerun; the initial run's CI timing flake reran successfully without a
code change and is not active product debt.

This ruleset is now load-bearing for every future PR into `feat/alpha-v0.1`, including
future documentation and implementation PRs.

## Baseline Debt Triage

**Baseline Debt Burn-down #2 — CLOSED / PASS (current).** PR #7 merged into the
protected branch, closing the remaining 14 historical IDs. The active
historical-failure allowlist is now **empty** (`eval/baselines/pytest-known-failures.json`
→ `failure_ids: []`, verified directly at protected HEAD `58cb06b`, unchanged since
`c760086`). Zero historical
allowance remains — any test failure from here on trips the baseline-gated check as a
regression. Overall trajectory across both burn-downs: **19 → 14 → 0**.

**Historical — Baseline Debt Burn-down #1 (CLOSED / PASS, PR #5):** IDs **3, 4, 5, 18, 19**
closed, bringing the allowlist from 19 to 14 IDs. The remaining 14 (deferred at that
point) were: **1/12** — A2 inspected both
(`tests/analyst_runtime/test_entity_resolution_barrier.py::test_resolved_entity_keeps_m3_and_analytics_paths_open`,
`tests/entities/test_canonical_entity_resolver.py::test_resolve_entity_action_serializes_safe_trace_and_m3_key_propagates`)
and added explicit A2 resolution-contract assertions to both, which pass; both still
failed at that time on a pre-existing, unrelated assertion (`payload["row_count"] == 10` /
an m2-sum total) against a real `run_sql` query result over `memory/agente_toesca_v2.db` —
live business-data drift, not stale trajectory/entity-resolution positioning. **2**
(source-truth verification), **6/7/9/10/11** (deferred until JLL cutover), **8** (PT
admin legacy expectation), and **13–17** (`db_chat` retirement/transition decision in A2 —
see `docs/a2-db-chat-transition-boundary.md`). Burn-down #2 (PR #7) subsequently closed
this full remaining set.

**Schema baseline contract:** the operational/local DB observed schema is **84**;
the tracked Git DB snapshot at this protected base is **81** (stale); the baseline
watermark is **84**; migration head is **91**. Migrations **085–091** remain JLL-gated
and outside the baseline. This does not independently verify live production. Unchanged
by Burn-down #2 — the business DB remained unchanged through the validated burn-down work.

**Key Track D conclusion (historical, from Burn-down #1 triage):** among the original 19
baseline failures, triage found no evidence of a current semantic/entity defect in the
canonical Analyst. This is a triage conclusion, not universal proof.

## Known debt / blockers

**Technical debt**
- `tools/datasets/catalog_v1.yaml` not yet updated for JLL v2's `v_rent_roll_semantic`
  contract (deliberately deferred to the cutover commit).
- Config for fondos duplicated across 4+ legacy structures (see Data Foundation above).
- Relationship between `db_chat.py`/`chat_bubble.js` and `analyst_runtime`: ownership is
  documented — see `docs/a2-db-chat-transition-boundary.md` (A2 caller/capability
  audit, A2 closed as PR #6). `db_chat.py`/`POST /api/chat` remain transition-only; the
  canonical runtime does not and must not import them (regression-guarded by
  `tests/test_analyst_architecture_contract.py`). Retirement itself is still not met (see
  that doc's retirement-signal checklist).
- The historical baseline-failure allowlist is now empty (Burn-down #1 + #2 closed it:
  19 → 14 → 0) — see Baseline Debt Triage above. There is no remaining tracked debt under
  the baseline gate; any new failure now trips it as a regression, not an allowed one.
- `docs/ROADMAP.md`'s A3 narrative (the "### A3 — Tools, SQL & Safety" section) still
  reads "immediate next slice A3.1 — SQL Safety ... not yet started as of this
  checkpoint," which is stale as of this checkpoint (A3.1–A3.3 are closed, see Snapshot
  above). This is **documentation debt only** — it does not mean A3.1 needs to be
  reopened or re-verified; A3.1's closure is independently evidenced by the PRs cited in
  the Snapshot table above. `ROADMAP.md` itself needs a follow-up edit, out of scope for
  this checkpoint.
- No design/spec document for any A3 sub-slice (A3.1a–A3.1e, A3.2a–A3.2f, A3.3) exists
  under `docs/` at this checkpoint — unlike the pattern established elsewhere in this repo
  (`docs/superpowers/specs/`, `docs/superpowers/plans/`). Scope-closure claims for A3 in
  this document rely on commit-message self-reporting, not an independently reviewable
  spec artifact. This is a traceability gap, not a reason to doubt the closures themselves
  — the commits and their tests are real and merged.

**Architectural debt**
- `agent.py`'s long-term role (which of its 102 tools survive) is an open question
  inherited from the archived `ROADMAP.md` and not yet re-decided under the current
  roadmap.
- `tools/factsheet_tools.py` (PPTX) still present, scheduled for removal, not yet removed.

**Business decisions (open, not technical)**
- UG (unidad de gestión) treatment in vacancy — rentable GLA or excluded? Migration 090
  makes the category visible; the inclusion decision itself is still pending.
- A `tasa_recaudacion` (collections-rate) KPI is deliberately not derivable yet — no
  invoice/document linkage exists to make recaudado/facturado a real cohort rate. Pending
  a business contract for what that rate should mean.

**WIP intentionally gated**
- JLL v2 production cutover (see JLL v2 section above) — gated on the official JLL file
  and a defined cutover process, not on missing code.

## Next exact steps

A2 — Agent Architecture, both Baseline Debt Burn-down blocks, and all of **A3.1 — SQL
Safety**, **A3.2 — Result + Evidence Contract**, and **A3.3 — Result Validation** are
closed (names per `docs/ROADMAP.md:169`). **A3.3 is not to be reopened** on the basis of
the post-closure conversational benchmark findings — see `docs/A3_POST_A3.3_GAP_REGISTER.md`.

What comes next is deliberately **not pre-committed** to A3.4 or A4 by this checkpoint.
`docs/ROADMAP.md` lists A3.4 (Trace / Retention / Auditability) as the next-in-sequence
slice and A4 (advanced intelligence) after it, but this sync's scope is documentation-only:
it registers four conversational gaps (A–D) found in benchmark analysis, classifies each by
evidence strength (confirmed / partially confirmed / plausible-not-demonstrated / not
reproduced), and recommends reproduction-with-trace before any of them becomes implementation
scope. Gap D (entity-set / enumeration deixis) is the one gap currently classified as a
confirmed architectural limitation; it motivates a future Conversation State v2 design memo,
which is explicitly **not** part of this checkpoint's scope. JLL v2 remains gated; see
`docs/ROADMAP.md` for the live roadmap.

## Auto-update design (not implemented)

No `scripts/update_current_state.py` exists. If written later, it should regenerate only
the block between `<!-- AUTO-GENERATED:START -->` and `<!-- AUTO-GENERATED:END -->` above,
additively and idempotently, failing loudly rather than guessing on any error (missing DB
file, failed query).

**Safe to derive mechanically**: current branch/HEAD SHA, latest migration filename,
live `schema_version` from an actual DB connection, presence/absence of
`.github/workflows/*`, test file counts (not pass/fail), JLL-related tag/branch presence
(existence only, never "deployed"), file presence for legacy components (to flag
still-present vs. removed).

**Must stay manual, forever**: architectural decisions and their rationale, business
decisions (Machalí exclusion, UG treatment, collections-rate definition), qualitative
blockers, roadmap priorities and sequencing rationale, any deployment-disposition claim
not verifiable from source (e.g. "JLL v2 is live in production"), and any PASS/FAIL claim
owned by a PR this document doesn't have direct access to at the time of writing (Eval
Foundation Step 0 was one such case — closed as PASS on 2026-09-01 once Track A reported
it; a future case of the same shape should be handled the same way: don't guess, wait for
the report, then record it here with its actual SHA/run ID).
