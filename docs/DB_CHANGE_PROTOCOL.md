# DB Change Protocol

**Status**: living document. Update it when the checklist below turns out to be wrong
or incomplete for a real change — don't let it drift into aspirational fiction.

This protocol governs any change to `memory/agente_toesca_v2.db` or the code paths that
read/write it: schema migrations, new ingestion pipelines, backfills, semantic
reclassifications, governance changes, and anything that changes what the Analyst can
query. It complements, and does not replace:

- `AGENTS.md` — non-negotiable DB/git safety rules (read first, always).
- `docs/CURRENT_STATE.md` — canonical snapshot of what's actually implemented/deployed.
- `docs/ARCHITECTURE.md` §3 — data-layer shape (`dim_*`/`raw_*`/`fact_*`/`derived_kpi`).
- `docs/db-poblar-fondos.md` — per-fund ingestion mechanics (CDG extract layout, etc.).
- `docs/superpowers/specs/2026-08-24-governed-analytics-expansion-design.md` — the
  governed-dataset/evidence-class contract this protocol's §6 references.

If this document ever contradicts one of those, the evidence-authority order in
`AGENTS.md` wins (code > migrations/schema > tests > CI > git history > `CURRENT_STATE.md`
> older narrative docs) — flag the contradiction, don't silently follow the stale one.

## 1. The fundamental rule: Git state ≠ DB state

`memory/agente_toesca_v2.db` is a SQLite file. It is **not** derivable from the repo at a
given commit unless you actually run `apply_migrations()` and the ingestion pipelines
against it. Two things being on the same commit does not mean they see the same data or
schema.

This already happened once, for real, in this repo — don't repeat it:

- **Baseline drift** (`tests/db/test_baseline.py`): migrations 2–22 were marked applied
  in production without ever having been executed. A fresh DB built by replaying
  `001..022` from `tools/db/migrations/` had a schema that **differed** from production's
  — tests validated a schema production didn't have, and vice versa. This is why
  `tools/db/baseline.sql` + `BASELINE_VERSION` (currently `84`) exist: a fresh DB is
  seeded from the consolidated baseline snapshot, not by replaying history.
- **JLL v2 schema-vs-production gap** (`docs/CURRENT_STATE.md`'s "JLL v2" section, current
  as of this writing): migrations `085`–`091` exist in `tools/db/migrations/` and are the
  highest version numbers in the repo, but **production is still on schema `84`**. The
  repo's migration head and the live DB's `schema_version` are two different facts — check
  both, never infer one from the other.
- **Parallel worktrees** (`.claude/worktrees/*`, `AGENTS.md`'s worktree-isolation rule):
  multiple agents can be working in separate worktrees off the same repo at the same time.
  A worktree checkout does **not** carry `memory/agente_toesca_v2.db` state with it in any
  meaningful way — the file at that path in a worktree may be stale, may be a copy someone
  made to unblock themselves, or may not reflect any commit at all. Never assume "same repo,
  same branch" implies "same DB." Never copy a `.db` file between worktrees to "sync" state
  without first establishing whose data would be destroyed and whose `schema_version`/
  `ingest_run` history it actually represents.

**Practical consequence**: reproducibility must be assembled from `schema/migrations` +
`baseline.sql` + ingestion code + source snapshots + reference/master data (`dim_*`
seeds) — never assumed from "it's in the DB file that's sitting in this checkout."

## 2. Scope

Apply this protocol to:

- Schema migrations (new tables/columns/views/indexes/constraints).
- New ingestion pipelines or new source formats for an existing pipeline.
- Backfills (`tools/db/backfill*.py`) and re-ingestion of a previously-loaded source.
- Semantic changes (redefining what a column/metric means, e.g. the `renta_uf` →
  `renta_semantica`/`renta_total_uf`/`renta_uf_m2` split in migration 091).
- Governance changes (`semantic/*.yaml`, `tools/datasets/catalog_v1.yaml`, evidence-class
  wiring in `tools/analyst_runtime/`).
- Anything that changes what the Analyst can query, resolve, or cite as evidence.
- Reference/master-data changes (`dim_fondo`, `dim_activo`, `dim_cuenta*`) that affect
  entity resolution or business semantics (e.g. the Apoquindo key ambiguity in
  `docs/matriz-claves-ambiguas-apoquindo.md`).

Routine, same-shape data loads (e.g. this month's rent roll landing in an
already-governed table via an already-tested ingestion script) don't need the full
checklist — normal test coverage and the existing dual-write/idempotency guarantees
apply. This protocol is for changes that alter shape, meaning, or reach, not for
recurring data refreshes.

## 3. Pre-change check

Before touching anything:

### Repository state
- `git branch --show-current`, `git rev-parse HEAD` — know which branch/worktree you're in
  (`AGENTS.md` §"Before making changes" already requires this for any change; restated
  here because it's load-bearing for DB work specifically).
- `git status` — if dirty with changes you didn't make, don't touch, stash, or revert them.
- If you're in a `.worktrees/<name>` checkout: confirm whether `memory/agente_toesca_v2.db`
  there is the real business DB, a stale copy, or absent. Don't assume.

### DB state
- Actual `schema_version`, checked directly (not assumed from the repo's migration head):
  ```bash
  python -X utf8 -c "
  import sqlite3; c=sqlite3.connect('memory/agente_toesca_v2.db')
  print('schema_version:', c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0])
  "
  ```
- Highest migration file present in `tools/db/migrations/` — compare against the above.
  A gap (like the current `84` vs `091` JLL v2 gap) is not necessarily a bug; it may be an
  intentional gate. Check `docs/CURRENT_STATE.md` before assuming either way.
- Whether another process/agent depends on this DB right now (parallel worktree work,
  a running ingesta_server session, an in-progress backfill).

### Classify the change
Tag it as one or more of: **SCHEMA**, **INGESTION**, **BACKFILL**, **SEMANTIC**,
**GOVERNANCE**, **ANALYST SURFACE**, **REFERENCE DATA**. The applicable sections below
depend on this classification.

## 4. Schema changes

- New migration file in `tools/db/migrations/`, numbered one past the current highest
  (currently `091`). `tools/db/connection.py::_discover_migrations` raises on duplicate
  version numbers — a collision fails loud, not silently.
- Migrations run inside a single transaction per file (`_execute_migration` /
  `apply_migrations`); write DDL so a partial failure doesn't leave a half-applied schema
  in a state `schema_version` doesn't reflect.
- If the change is meant to eventually become part of a fresh DB's baseline, remember
  `baseline.sql` + `BASELINE_VERSION` are a **snapshot**, not auto-derived — someone
  regenerates them deliberately (`scripts/regenerar_baseline.py`), and `BASELINE_VERSION`
  must be bumped when they do. Don't assume a new migration is automatically reflected in
  `baseline.sql`.
- Preserve existing data — additive by default (`ADD COLUMN`, new tables/views). If a
  migration is destructive (drops/renames a column, changes a type), document the
  business decision behind it in the migration file's own header comment, following the
  precedent in `087`/`090`/`091`.
- Update `tests/db/test_invariantes.py` if the change introduces a new invariant worth
  protecting (canonical-key checks, FK integrity, vocabulary checks — see existing tests
  there for the pattern), and confirm `tests/db/test_baseline.py` still passes: it checks
  that a fresh baseline-built DB matches an upgraded-from-scratch DB, not just that
  migrations apply without erroring.
- Check downstream consumers before merging: `tools/db/repo_*.py`, `tools/datasets/
  catalog_v1.yaml`, `semantic/schema/`, report/factsheet generators
  (`scripts/build_factsheet.py`), and `tools/analyst_runtime/` if the changed
  table/view is Analyst-reachable.

## 5. Ingestion changes (new source, new pipeline, backfill, re-ingestion)

Document, at minimum:

**Source**
- Provider, source file/API, format version, acquisition date, reporting period(s)
  covered, and — where the pipeline supports it — the file hash used for idempotency
  (`file_hash` gating, per `AGENTS.md`'s "all inserts must be idempotent" rule).

**Coverage**
- Entities and periods covered, expected granularity, records read vs. accepted vs.
  rejected/skipped, how duplicates and nulls are handled.

**Semantics** — do not infer from column names alone:
- Metric meaning, unit (CLP vs UF — note `raw_er_activo_line.monto_clp` holds UF for
  recent Apo/PT ER per `AGENTS.md`; don't assume the column name is authoritative),
  currency, stock vs. flow, entity granularity, period granularity, aggregation rule.
- If the source overloads a field with more than one meaning (the pre-091 `renta_uf`
  case), consider whether it needs the same kind of explicit-field split rather than
  layering more interpretation logic on top of an ambiguous column.

**Post-ingestion validation** — check at least:
- Row counts, duplicate count, rejected-row count, null rates, period/entity coverage,
  units, plausible-range check.
- For financial data: totals reconcile against subtotals/components (see
  `feedback_gastos_check_suma` convention — sum of expense components must equal the
  reported total), period continuity, cross-source consistency where a second source
  exists for the same fact.
- Compare against the original source document when the numbers matter for a KPI the
  Analyst or a fact sheet will cite.

## 6. Governance classification

The Analyst's evidence system (`tools/analyst_runtime/`) recognizes three evidence
classes today — use this exact vocabulary, not the generic terms from older design docs:

- `canonical_metric` — single authoritative fact, validated by `canonical_guard.py`
  (deprecated as production path per `docs/CURRENT_STATE.md`, but still the parity
  reference for `coverage_guard.py`).
- `governed_dataset` — multi-row/coverage-checked data backed by the `semantic/` +
  `tools/datasets/` contract (`catalog_v1.yaml`, `executor.py`).
- `controlled_sql` — supporting evidence from a scoped, non-free-form query
  (`sqlite_guard.py`-gated), not citeable as a standalone claim on its own.

A new dataset/metric does not get to claim `canonical_metric` or `governed_dataset`
status just because it's queryable via SQL. Classification requires:
- An entry in `semantic/metrics/` (or `entities.yaml`/`relationships.yaml` as
  applicable) and, for tabular data, a `tools/datasets/catalog_v1.yaml` entry.
- Documented authority (who/what makes this the source of truth), provenance, temporal
  scope, known limitations, and coverage.
- Awareness that the catalog can be *intentionally* behind the schema — see
  `docs/CURRENT_STATE.md`'s note on `catalog_v1.yaml:59` still declaring the pre-091
  `renta_uf` mapping on purpose, pending the production cutover. Don't "fix" a
  deliberately-deferred catalog entry without checking `CURRENT_STATE.md` first.

## 7. Analyst integration check

If the change is meant to make data Analyst-queryable, verify the full chain, not just
that the data exists in a table:

Discovery → entity resolution → tool selection → argument construction → retrieval →
evidence classification → coverage/canonical guard → final answer.

Explicitly distinguish, in whatever you write up:

> "the data does not exist" vs. "the data exists but retrieval/wiring failed"

This distinction matters for how the system's governance is trusted — a false "no data"
answer erodes trust differently than a wiring bug. The JLL v2 pipeline is the concrete
precedent for the second case: migrations `085`–`091` populate real tables in sandbox,
but zero code in `tools/analyst_runtime/` or `web/analyst.html` references them — the
Analyst cannot see this data yet, and that is a documented "not wired up," not a bug to
route around silently.

## 8. Test and eval coverage

- Run the relevant suite before claiming anything works: `pytest tests/db/`,
  `pytest tests/analyst_runtime/` if Analyst-facing, `pytest tests/` for a full pass.
- CI is load-bearing on `feat/alpha-v0.1` (`tests (baseline-gated)`,
  `eval/benchmark/tests`, `eval/product_alpha/tests` — no bypass; see
  `docs/CURRENT_STATE.md`'s "Eval & Observability" section for the exact gate behavior).
  Running these locally first is expected, not optional.
- For changes with real user-facing impact, consider what `eval/benchmark/cases/` or
  `eval/product_alpha/cases.py` case would catch a regression: a positive case, a
  genuine-absence case, a boundary case, a semantic-misread case. Add/update a case if
  the change affects Analyst behavior in a way the current suite wouldn't exercise.

## 9. Reproducibility

For any dataset this protocol applies to, be able to answer: **"how do we rebuild this
from scratch?"** The target shape is:

```
source snapshot + schema/migrations + ingestion code + deterministic transforms
+ reference/master data (dim_*)
= reproducible DB state
```

If a given dataset can't currently be rebuilt this way (e.g. an ingestion step is
manual, a spreadsheet input isn't archived anywhere versioned), say so plainly —
`REPRODUCIBILITY: NOT YET REPRODUCIBLE`, plus what's missing — rather than letting the
gap go unstated. This mirrors `docs/ARCHITECTURE.md` §8's divergence-tracking rule:
record the gap, don't silently paper over it.

## 10. Live DB safety

Never run against `memory/agente_toesca_v2.db` (or any worktree's copy of it) without
knowing who else depends on it. Without explicit coordination, do not:

- `git reset --hard`, `git clean -f`, `git checkout .` in a directory containing the DB.
- Delete, overwrite, or replace `memory/agente_toesca_v2.db`.
- Restore an older DB snapshot over the current one.
- Copy a `.db` file from one worktree into another to "fix" a state mismatch.

These are already blanket-prohibited by `AGENTS.md`'s git-safety rules; this section
exists to make explicit that the same caution applies to the `.db` file itself, which
git safety commands don't protect (it's not necessarily tracked, and `git status` won't
warn you before you `cp` over it).

## 11. Change record (for material changes)

For SCHEMA/GOVERNANCE/ANALYST-SURFACE changes and any backfill touching production data,
record this somewhere durable (PR description, or a dated note under `docs/` if the
change is large enough to warrant one) — this is intentionally lighter than the fuller
proposal drafted for this doc, to avoid bureaucracy for routine ingestion:

```
Change: <one line>
Classification: SCHEMA | INGESTION | BACKFILL | SEMANTIC | GOVERNANCE | ANALYST SURFACE | REFERENCE DATA
Branch / HEAD:
Schema version before -> after:
Source(s) / provenance:
Governance classification (if new dataset/metric): canonical_metric | governed_dataset | controlled_sql | not yet classified
Analyst impact: none | wired | not-yet-wired (be explicit which)
Tests / evals touched:
Reproducibility: reproducible | NOT YET REPRODUCIBLE (+ what's missing)
```

Also add a `wiki/log.md` entry (`## [YYYY-MM-DD] tipo | Descripción`) per `CLAUDE.md`'s
wiki-maintenance rule if the change resolved something worth remembering for future
sessions.

## 12. When to update `docs/CURRENT_STATE.md`

Only when the change alters a **capability, architecture, or production-deployment
fact** — e.g. a migration actually gets applied to production, the Analyst becomes able
to query a previously-unreachable dataset, a known-debt item gets closed. Routine data
refreshes, same-shape monthly ingestion, or an internal-only schema addition that
doesn't change what the system can do do **not** require a `CURRENT_STATE.md` edit.
When in doubt, ask: "does this change what someone reading `CURRENT_STATE.md` would
believe is true about the system?" — if no, skip it.

## 13. Completion checklist

```
[ ] Change classified (§2)
[ ] Repository/worktree state checked, DB dependents identified (§3)
[ ] schema_version checked directly, not assumed from repo migration head (§3)
[ ] Migration created/reviewed, baseline.sql reviewed if applicable (§4)
[ ] Dependent code reviewed (repos, catalog, semantic layer, Analyst runtime) (§4)
[ ] Source/provenance recorded (§5)
[ ] Coverage and semantics validated, not inferred from column names (§5)
[ ] Post-ingestion validation run (§5)
[ ] Governance classification assigned using canonical_metric/governed_dataset/controlled_sql (§6)
[ ] Analyst queryability checked end-to-end if applicable; absence vs. wiring-failure distinguished (§7)
[ ] Relevant tests/invariants added or updated (§4, §8)
[ ] Relevant evals added/updated if Analyst behavior changes (§8)
[ ] Reproducibility assessed and stated explicitly, including NOT YET REPRODUCIBLE if true (§9)
[ ] No destructive operation run on the live DB without explicit coordination (§10)
[ ] Change record written for material changes (§11)
[ ] CURRENT_STATE.md updated only if a capability/architecture/production fact changed (§12)
[ ] git checkpoint recorded (commit, not pushed/merged unless explicitly asked)
```
