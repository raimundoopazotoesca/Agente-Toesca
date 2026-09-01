# CODEX.md — Codex-specific notes (Toesca Automation Agent)

Universal rules (DB safety, git safety, worktree isolation, testing) live in
`AGENTS.md`. Current state lives in `docs/CURRENT_STATE.md`. This file only covers what's
different about working as Codex on this project — it does not restate state or
architecture, both of which drift and are tracked canonically elsewhere.

## Priority order

1. User/system instructions.
2. `AGENTS.md` — non-negotiable rules for any coding agent.
3. `docs/CURRENT_STATE.md` — canonical current state (not this file).
4. `wiki/index.md` + `wiki/log.md` — living domain memory, can supersede older docs.
5. `docs/` — plans and guides; some historical files lag reality. If a doc conflicts
   with code/DB, verify against code/DB and trust that over the doc.

## Codex-specific behavior

- **Do not commit or push unless the user explicitly asks, or the flow clearly
  requires it and that's unambiguous.** This differs from the wiki-update convention in
  `CLAUDE.md` (which assumes commit/push after a wiki edit) — as Codex, default to not
  committing.
- Respect a dirty worktree: never revert changes you didn't make.
- Don't invent paths, tool results, figures, dates, or filenames.

## How to continue a session

1. Check `git status --short`.
2. Read the latest entries in `wiki/log.md`.
3. If it's a per-fund ingestion task, read `docs/db-poblar-fondos.md` first.
4. Query the real DB before acting if the task depends on current state — don't trust
   a number from a doc.
5. Prefer existing helpers/repos over ad-hoc SQL in production code.
6. Make minimal changes and verify them (run the relevant tests — see `AGENTS.md`'s
   testing section for required-check names; CI is active and load-bearing on the
   protected branch, `docs/CURRENT_STATE.md` has the gate detail).
7. If you learn something durable, update the wiki and its log per `CLAUDE.md`'s wiki
   rules — as Codex, don't commit/push that update unless asked.
