# Toesca Analyst Benchmark — findings log

Observations produced *by running the benchmark*, not design decisions.
Findings about the systems under test (Track A, Track B, providers) live
here. Findings about the benchmark's own data/coverage gaps live in
`PENDING.md`.

---

## 2026-08-13 — Track A: 0/8 L3–L5 analytical coverage

Ran all 8 L3–L5 pilot cases (`tae-l3-001`, `tae-l3-002`, `tae-l4-001..003`,
`tae-l5-001..003`) against Track A (`tools.db_chat.answer`, wrapped by
`adapters/track_a_structured.py`). **All 8 produced the identical generic
clarification message**, verbatim:

> ¿Podrías especificar qué métrica te interesa (ej. vacancia, NOI, TIR,
> dividend yield) y a qué fondo o activo te refieres (TRI, PT, Apo, o un
> activo específico)?

This happened even when the question named the fund/asset/period
explicitly and unambiguously (`tae-l4-002`: "vacancia del fondo TRI en
enero de 2026... su repunte en febrero" — still clarified; `tae-l5-003`:
"el fondo Apo" — still clarified). `Turn.queries` was empty in all 8 turns:
no SQL was traced by the sandbox for any of them.

**Reading:** this is not "lower quality analysis" — it's zero attempts.
Track A's intent layer appears to require the question to match a narrow
template (a single explicit metric keyword, single entity) before it will
proceed past clarification; anything shaped like an open-ended summary,
diagnosis, or investigation question falls through to the same canned
fallback regardless of how well-specified it actually is.

**Decision (user, 2026-08-13):** do not patch Track A to fix this — it's
exactly the kind of architecture-vs-product gap this benchmark exists to
surface. Recorded as-is. Do not use these 8 non-answers to calibrate the
rubric judge — there's no reasoning in them to calibrate against.

**Consequence for rubric design:** the pilot could not validate the
rubric's judge-territory dimensions (`analytical_quality`,
`investigation_quality`, `grounding`, etc.) against real reasoning, because
Track A never produced any. Rubric calibration needs a track that actually
attempts L3–L5 — see Track B below.

---

## 2026-08-13 — Gemini's OpenAI-compat endpoint breaks on replayed tool calls

While building Track B (`adapters/track_b_frontier.py`), a multi-turn tool
loop against `gemini-flash-latest` via
`https://generativelanguage.googleapis.com/v1beta/openai/` failed on the
turn *after* a tool call, whether or not Gemini was the provider for the
first call too:

```
openai.BadRequestError: Error code: 400 - Function call is missing a
thought_signature in functionCall parts. This is required for tools to
work correctly... function call `default_api:run_sql`, position 2.
```

Gemini's compat layer expects its own `thought_signature` metadata echoed
back on a replayed assistant `tool_calls` message; a standard
OpenAI-shaped reconstruction (the one every other provider tested here
accepts) doesn't carry it. This is a Gemini-specific quirk, not a bug in
Track B's loop — reproduced identically with Gemini as the sole provider
for the whole conversation, ruling out cross-provider replay as the cause.

**Consequence:** Gemini is not currently usable as Track B's provider for
anything beyond a single-tool-call exchange, unless the adapter is
extended to capture and replay Gemini's raw response metadata verbatim
(out of scope for "deliberately minimal"). Track B pins one provider per
session for a different, related reason (see its docstring) — this finding
is why Gemini specifically is excluded from that pin's viable options
today.

---

## 2026-08-13 — Track B live pilot run: blocked by provider exhaustion, not by Track B

Attempted to run the same 8 L3–L5 pilots against Track B after implementing
and passing 17 mocked/deterministic tool-loop tests. At run time, every
configured provider with a working key was unavailable within this
session:

| Provider | Model | Result |
|---|---|---|
| groq | llama-3.3-70b-versatile | `429` daily token quota exhausted (99,543/100,000 TPD) — consumed by this session's Track A pilot runs + earlier smoke tests, not by Track B itself |
| mistral | mistral-large-latest | `429` rate limit (retried once, still limited) |
| sambanova | gpt-oss-120b | `429` "experiencing high demand" |
| gemini | gemini-flash-latest | `400` thought_signature incompatibility (see finding above) — orthogonal to quota |
| deepseek | — | no API key configured in this environment |

Per instructions, stopped here rather than burning further quota/time
chasing availability. **Track B itself is implemented and tested; it has
not yet produced a live analytical response.** The live pilot run against
Track B is the next step once a provider has headroom (retry after the
Groq quota window, or supply a fresh key for any OpenAI-tool-calling-
compatible provider other than Gemini).

---

## 2026-08-13 — Track B live pilot run: completed on Mistral, gpt-oss-120b/llama-70b unusable in practice

Retried the same 8 L3–L5 cases. Isolated availability probes (trivial
non-tool call, then a real tool-calling call) in priority order:

| Priority | Provider/model | Probe result |
|---|---|---|
| 1 | groq / openai/gpt-oss-120b | Tool-calling probe succeeded on 3 separate accounts (keys 1/2/3) but the account's 8000 TPM (tokens-per-minute) ceiling was hit on the **first real call** every time — Track B's system prompt (semantic context + full DB schema) alone is ~5800–6100 tokens, ~72–76% of the whole per-minute budget. Structural, not account-specific. |
| 2 | groq / llama-3.3-70b-versatile | Trivial ping succeeded (near-zero tokens), but the real system-prompt-sized call hit each account's **daily** quota (TPD) at 98,000+/100,000 on all 3 keys — consumed cumulatively by this session's own Track A pilot runs and probes. |
| 3 | mistral / mistral-large-latest | Available. Used for the full run. |
| 4 (sambanova) | not probed — priority 3 succeeded, so per instructions did not fall further |

Pinned mistral-large-latest for the whole run, no cross-model fallback.
Runner-level retry with visible backoff around whole `ask()` calls (not
inside Track B's loop) handled Mistral's own rate limiting, which was
frequent (15s cooldown, up to 8 attempts). **Full transcript**:
`eval/benchmark/results/track_b_l3l5_pilot_2026-08-13.txt`.

**Outcome: 6/8 cases produced a real answer, 2/8 exhausted retries
(infra, not a Track B defect) — a categorically different result from
Track A's 0/8.** See the chat report for the full per-case breakdown;
summary here:

- **Best case** (`tae-l4-001`, Strip Machalí divestment diagnosis): 5 tool
  calls, correctly used `dim_activo.vigente_hasta`, correctly concluded
  "fund exit, not a data error" — the target behavior for that case.
- **Best quantitative case** (`tae-l5-002`, vacancia ranking): identified
  Apo3001 at 36.2% vacancy (ground truth: 36.3%), transparently flagged
  that some peer assets only had data through May, not June. Full marks
  on `factual_correctness`/`conversational_quality`.
- **Real grounding failure found** (`tae-l4-002`, TRI vacancia swing):
  attributed the dip/rebound to **Viña Centro**, when the SQL-verified
  driver is **Mall Curicó** — then invented an unsupported "reporting
  error" hypothesis on top of the wrong attribution. This is exactly the
  kind of failure `forbidden_claims`/grounding scoring exists to catch;
  currently un-caught because the judge isn't built yet.
- **Appropriate hedge, not a failure** (`tae-l4-003`, TIR serie I): never
  found the right nemotécnico (`CFITOERI1I`; it searched `TRI-I`), got no
  rows, and explicitly said it could not confirm a cause rather than
  inventing a number — good epistemic behavior wrapped around a real
  retrieval miss.
- **2 infra failures** (`tae-l3-001`, `tae-l5-001`): exhausted 8 retries
  against Mistral's rate limiter before an answer was produced. Not
  scored as model failures — no response was ever generated.

**Gemini's incompatibility remains an adapter/protocol issue, not a model
capability judgment** — untouched this pass, exactly as instructed.
