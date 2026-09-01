# CLAUDE.md — Claude-specific notes (Toesca Automation Agent)

Universal rules (DB safety, git safety, worktree isolation, testing) live in
`AGENTS.md` — read that first. Current state lives in `docs/CURRENT_STATE.md`.
Architecture lives in `docs/ARCHITECTURE.md`. Roadmap lives in `docs/ROADMAP.md`. This
file only covers what's specific to working as Claude on this project.

## Wiki maintenance

The cumulative agent wiki lives in `wiki/` (Obsidian vault — open the `wiki/` folder as
the vault).

1. **Before exploring code you might have already documented**, read `wiki/index.md`.
2. **Before searching for a file in SharePoint**, read `wiki/sharepoint/index.md` — it
   has the full tree with naming patterns per folder. Don't scan the disk if the answer
   is already there.
3. **When you learn something new** (a resolved error, a process detail, unexpected
   behavior), update the relevant wiki page and the log.
4. **When answering domain questions** (funds, assets, processes), read the relevant
   wiki pages first.
5. Add an entry to `wiki/log.md` formatted `## [YYYY-MM-DD] tipo | Descripción`.
6. After any wiki update, commit **only the wiki files you changed** (never
   `git add -A`) and push — but only when the user has asked for a commit/push, per the
   global policy of not committing unless explicitly requested.

## Resource allocation — pick the cheapest tool that can do the job

| Task | Resource |
|---|---|
| Architecture, complex reasoning, multi-step decisions | Claude Opus (this model) |
| Mechanical code, simple functions, 1–2 file fixes | Codex (`/codex:rescue`) |
| Diff/new-code review | Codex (`/codex:review`) |
| Codebase exploration, file search | `Explore` subagent |
| Non-trivial implementation planning | `Plan` subagent |
| Independent simultaneous tasks | Multiple subagents in parallel |
| Simple edits, short answers | Inline, no subagent |

**Standing efficiency rules:**
1. Read `MEMORY.md` before re-exploring code you've already seen.
2. Parallelize independent tool calls in a single message.
3. Use Codex for mechanical code — it doesn't consume Anthropic tokens.
4. Only launch subagents for searches that would take >3 queries; do 1–2 query
   lookups inline.
5. Read only the section of a file you need — never the whole file if you don't have to.
6. If memory or context already has the answer, don't re-search the code.

## Ingesta server auth (still true, worth restating here)

Every `/api/*` route on `scripts/ingesta_server.py` requires the `X-Ingesta-Token`
header. The token comes from `.env`'s `INGESTA_TOKEN` or is generated per session and
printed at startup; it's auto-injected into pages the server serves. **Open the
Analyst/factsheet from `http://127.0.0.1:8765/...`, not by double-clicking a file** —
`file://` doesn't carry the token and you'll get a 401.
