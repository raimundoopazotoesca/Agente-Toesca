# db_chat transition boundary (A2)

## Scope of this audit

A2 does not delete or feature-develop `tools/db_chat.py`. This document records the
caller/capability audit required by A2-D5 so retirement is a documented decision, not a
guess, and so the canonical Analyst runtime does not silently pick up a new dependency on
it.

## Callers verified in-repo (base `fdc253b5167b8dbce595fa079450d6da2235497b`)

`grep -rl "db_chat"` outside `tests/` and `eval/` returns:

| File | Relationship |
|---|---|
| `tools/db_chat.py` | the module itself |
| `scripts/ingesta_server.py` | imports `db_chat` and calls `db_chat.answer(...)` from exactly one route, `POST /api/chat` (line ~564); also serves `web/chat_bubble.js` at `GET /chat_bubble.js` |
| `tools/analyst/ambiguity.py`, `tools/analyst/context_builder.py`, `tools/analyst/intent.py` | `db_chat`'s own internal helper modules (`tools/analyst/`), a different package from the canonical `tools/analyst_runtime/` and `tools/analyst_workspace/` |
| `tools/eval/__init__.py` | a docstring disclaiming a dependency, not an import |

`web/chat_bubble.js` is loaded by `scripts/build_factsheet.py` into the generated
factsheet HTML output, and served directly by `scripts/ingesta_server.py`'s
`GET /chat_bubble.js` route.

`tests/test_db_chat.py` exercises `db_chat` directly (contains baseline allowlist IDs
13–17); `eval/`-side adapters intentionally measure the old surface for comparison, not as
a production dependency.

**No file under `tools/analyst_runtime/` or `tools/analyst_workspace/` imports
`tools.db_chat`** — verified by `tests/test_analyst_architecture_contract.py::test_canonical_runtime_does_not_import_db_chat`,
which greps the canonical runtime/persistence source files as a standing regression guard.

## Unique capabilities not (yet) in the canonical Analyst

- Multi-provider fallback chain (`DB_CHAT_PROVIDER` default `groq`, fallback
  `deepseek → groq → gemini → mistral → sambanova`).
- The legacy client-history wire protocol consumed by `chat_bubble.js` (client-supplied
  `history` array, `conversation_id`/IP-derived `session_id`).
- Markdown chart/table rendering conventions in `chat_bubble.js`.

None of these are canonical-Analyst dependencies; they are exclusively `db_chat`/bubble
concerns.

## Retirement signal (not yet met)

Per the approved A2-D5 scope, retiring `db_chat.py` / `POST /api/chat` requires **all** of:

1. Zero non-test callers of the route (currently: one route handler, one bubble load site,
   both still live).
2. `chat_bubble.js` no longer load-bearing in the shipped factsheet output.
3. The unique capabilities above either superseded by the canonical Analyst or a deliberate
   decision to drop them.
4. Baseline allowlist IDs 13–17 (`tests/test_db_chat.py`) retired with code, or explicitly
   re-scoped as no longer architecture debt.

None of these conditions hold at this checkpoint. `db_chat.py` and `POST /api/chat` remain
**transition-only**: still served, not extended, not imported by the canonical runtime.
