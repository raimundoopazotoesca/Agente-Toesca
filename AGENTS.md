# AGENTS.md — Universal Rules for Coding Agents (Toesca)

These rules apply to any coding agent (Claude, Codex, or otherwise) working in this
repo. Tool-specific notes live in `CLAUDE.md` / `CODEX.md` — read this file first.

## Before making changes

1. **Inspect branch/worktree/HEAD** — `git branch --show-current`, `git rev-parse HEAD`.
   Know which branch and worktree you're in before touching anything.
2. **Inspect `git status`** — never act on a repo you haven't looked at. If it's dirty
   with changes you didn't make, don't revert, stash, or clean them without asking.
3. **Read `docs/CURRENT_STATE.md`** — this is the canonical source for what actually
   exists right now (product surfaces, data foundation, JLL v2 status, known debt). It
   supersedes any date-stamped claim in this file, `CLAUDE.md`, `CODEX.md`, or `wiki/`.
4. **Read the relevant architecture/domain docs** — `docs/ARCHITECTURE.md` for
   component structure; `wiki/index.md` for domain knowledge (fund structure, processes,
   KPI methodology) before touching anything you haven't already explored.
5. **Reconstruct evidence before acting.** Don't assume a doc is correct — check it
   against code, migrations, tests, and git history first.

**If a doc contradicts code/tests/migrations: repo evidence wins.** Flag the doc as
stale rather than trusting it. This includes this file — if something below is out of
date, say so rather than following it blindly.

## Evidence authority order

1. Code
2. Migrations / schema
3. Tests
4. CI / workflows (active and load-bearing on the protected branch — see
   `docs/CURRENT_STATE.md` for the required checks and gate detail)
5. Git history / branches / tags
6. Docs recently marked as current design (`docs/CURRENT_STATE.md`, `docs/ROADMAP.md`,
   `docs/ARCHITECTURE.md`)
7. Older narrative docs (treat as historical unless independently re-verified)

## Git safety

- **NEVER `git add -A` or `git add .`.** Stage files explicitly by name. This repo's
  working tree routinely carries untracked `.db` backups, log files, and sandbox
  artifacts that must never be committed.
- **NEVER `git reset --hard`, `git clean -f`, `git checkout .`, or stash/discard changes
  you didn't make** without explicit authorization. Run `git status` first, always.
- **Worktree isolation**: if you're working in a `.worktrees/<name>` directory, stay
  inside it. Never edit, reset, stash, or touch files in another worktree or the main
  checkout, even if a task references work happening there in parallel.
- Prefer small, semantic commits. Don't push or open a PR unless explicitly asked.

## Database rules

- **Business DB = `memory/agente_toesca_v2.db`.** Never `memory/agente_toesca.db` (empty,
  legacy — ignore it) and never a `v1` path.
- **Agent-state DB = `memory/agente_state.db`** (chat history, per-user context/KPIs) —
  separate from the business DB, managed via `tools/memory_tools.py`.
- Filter `WHERE superseded_at IS NULL` on every versioned raw table read for
  business logic. This repo's versioning convention is append-only with logical
  tombstones — never delete a superseded row, never read one without the filter.
- All inserts must be idempotent — check `file_hash` before assuming a fresh load.
- **Machalí is excluded from the portfolio.** No ingestion, no calculations, no
  aggregations include it.
- `fondo_key` canonical values are `PT`, `TRI`, `Apo` (never "A&R PT", "Rentas
  Apoquindo," etc.). `APO` (uppercase) is only an **input alias** used by some CLI
  scripts/prompts — `tools.db.fondo_keys.fondo_canonico()` converts it before persisting.
  Writing `APO` directly to `dim_fondo`-referencing tables violates the FK; an invariant
  in `tests/db/test_invariantes.py` protects this.
- Four distinct Apoquindo-related keys exist — never infer the relationship from the
  name, always check `fondo_key`/`dim_activo`: `Apo` (fondo), `Apo4501` (activo, fondo
  Apo), `Apo4700` (activo, fondo Apo), `Apo3001` (activo, fondo **TRI**, not Apo). See
  `docs/matriz-claves-ambiguas-apoquindo.md` for the full picture, including two
  legacy-mislabeled `derived_kpi` entities (`Apoquindo`, `Fondo Apoquindo`) that the
  Analyst still exposes as valid keys — don't rename them without updating
  `noi_query.py` and `db_chat.py` in the same commit.
- **Never read the full CDG spreadsheet** (`*Control De Gestión*.xlsx`, ~14 MB) — use
  the lightweight extract at `work/eeff_ingesta/TRI/cdg_extract.xlsx` instead.
- Always run Python with `python -X utf8` on Windows (avoids cp1252 console issues).
- **DB first** for data questions. Open Excel/SharePoint only if the DB has no coverage
  or you're actively ingesting/verifying a source.

## No invented verification

**Never claim something was checked, tested, or verified unless you actually ran the
command.** If you didn't execute a query or test, say so — don't imply you did. This
applies to schema state, test results, and data values alike.

To check current DB state yourself rather than trusting a stale number in any doc:

```bash
python -X utf8 -c "
import sqlite3; c=sqlite3.connect('memory/agente_toesca_v2.db')
print('schema_version:', c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0])
"
```

## Testing expectations

- Run the relevant test suite before claiming a change works: `pytest tests/db`,
  `pytest tests/` for a broader check.
- If you add a migration, add or update the corresponding invariant test in
  `tests/db/test_invariantes.py` and check `tests/db/test_baseline.py` still passes —
  it verifies a fresh-head DB matches an upgraded-production DB, not just that
  migrations apply cleanly in isolation.
- CI exists and is load-bearing on the protected branch (`feat/alpha-v0.1`) — required
  checks (`tests (baseline-gated)`, `eval/benchmark/tests`, `eval/product_alpha/tests`)
  are enforced by an active GitHub ruleset with no bypass. See `docs/CURRENT_STATE.md`
  for the exact required-check names and gate behavior. Running tests locally before
  claiming success is still not optional — it's what CI will check anyway, and you
  should know the result before pushing, not after.

## Semantic / data invariants

- `dim_cuenta_eeff` has no `signo` column — the accounting sign is already applied in
  `raw_eeff_line.monto_clp`.
- `periodo` is always `YYYY-MM` (string); ingestion must truncate `YYYY-MM-DD →
  YYYY-MM` on persist.
- `loaded_at` is always `'YYYY-MM-DD HH:MM:SS'` (no `T`) in most tables; `fact_adquisicion`
  and `fact_tasacion` still default to an ISO format with `T` for new rows until those
  tables are recreated.
- `raw_er_activo_line.monto_clp` holds UF values (not CLP) for recent Apo/PT ER
  ingestions, by inherited convention. Do not "fix" this without checking every
  downstream consumer first.
- Don't assume the semantic catalog (`tools/datasets/catalog_v1.yaml`) reflects the
  latest migration's view definitions — see `docs/CURRENT_STATE.md`'s JLL v2 section for
  a live example of a deliberately-deferred catalog update.

## Pointers to specialized docs

- **Ingesting data for a specific fund**: `docs/db-poblar-fondos.md` — read before
  touching any ingestion script.
- **Long-session continuity for Codex**: `CODEX.md`.
- **Wiki (domain knowledge)**: `wiki/index.md` — read before exploring code you might
  have already documented, and before answering domain questions (funds, assets,
  processes). `wiki/sharepoint/index.md` has the SharePoint folder tree — don't scan the
  disk if the answer is already there.
- **KPI methodology**: `wiki/kpis_rentabilidad_fondos.md`, `wiki/tir_contable_desde_inicio.md`,
  `wiki/kpis_noi_cap_rate_apo.md`.

## Stack notes

- Python 3.11+, SQLite, `openpyxl` (use `read_only=True` + `iter_rows(values_only=True)`
  for large files — never `ws.cell(row, col)` in read-only mode, it's O(n)).
- `pywin32` for Outlook (COM) — Windows-only, used by the legacy `agent.py` surface.
- Rutas: use forward slashes or raw strings in Python paths (avoid `\U`, `\n` escaping
  surprises on Windows paths).
- Chilean number format: `"1.234.567"` → `1234567.0` (dots = thousands, no decimals);
  `"1.234,56"` → `1234.56` (dot = thousands, comma = decimal).
- Excel date serial: `(date - date(1899, 12, 30)).days`.

## Adding a new tool to `agent.py` (legacy surface only)

1. Create the function in `tools/<name>.py`.
2. Import it in `tools/registry.py`.
3. Add an entry to `TOOL_DEFINITIONS` in `registry.py`.
4. Add the dispatch lambda in `_dispatch` in `registry.py`.

This applies only to the legacy 102-tool `agent.py` surface — the Analyst
(`tools/analyst_runtime/`) has its own, separate mechanism; see `docs/ARCHITECTURE.md`.
