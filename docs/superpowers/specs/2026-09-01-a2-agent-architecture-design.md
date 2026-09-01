# A2 Agent Architecture Design

## Scope

A2 closes the architectural contract of the existing canonical Analyst at protected base `fdc253b5167b8dbce595fa079450d6da2235497b`. It is not a product redesign.

Canonical lifecycle:

`/analyst -> /api/analyst/* -> analyst_api -> ConversationService -> AnalystSession -> AnalystLoop -> governed actions/evidence`.

`tools/db_chat.py` and `POST /api/chat` remain transition-only. The canonical runtime must not import them.

## Component ownership

| Component | Current responsibility | A2 disposition | Owner after A2 |
|---|---|---|---|
| `analyst_loop.py` | provider-neutral investigation, action dispatch | KEEP; expose actual trajectory | A2 |
| `session.py` | finalization, evidence selection, coverage/presentation | EXTEND with trace inputs | A2 |
| `conversation_service.py` | persist messages, hydrate sessions | EXTEND with correlation and trace persistence | A2 |
| `store.py` | workspace SQLite and message metadata | KEEP; assistant metadata is trace persistence seam | A2 |
| `entities/resolver.py` | entity candidates/internal status | EXTEND through outcome adapter | A2 |
| analytics catalog/actions | metric capability and period-bearing facts | EXTEND only through adapters | A2 |
| guards/evidence | SQL read-only, claim/coverage evidence | KEEP | A3 extends validation |
| semantic conversation behavior | replay/durable evidence exists, no specified replacement semantics | DEFER | A4 |
| eval scoring/analytics | existing suites and blueprint | DEFER | A5 |
| `db_chat.py`, `/api/chat`, bubble | prior-generation chat | TRANSITION | retirement decision |

ConversationService is persistence/orchestration infrastructure, not an “A4 service.” A4 owns semantic inheritance, corrections, topic reset, and replacement semantics.

## TurnTrace v1

### Shape

Create a JSON-safe, versioned trace representation with `trace_version: "1"`. It includes only structured, observable data:

- identity: `turn_id`, conversation/session IDs, timestamp, span type, code version when available;
- input: visible user text;
- resolution: entity, metric, and period outcomes;
- routing: actual terminal route, reason code, selected actions;
- execution: sanitized action arguments, action trace metadata, emitted SQL, knowable tables/views, evidence references, latency;
- model: observable provider/model/calls/retries and usage;
- output: final visible answer, evidence references, termination reason;
- validation: only currently-existing validation results.

It never includes provider raw/replay payloads, prompts, chain-of-thought, hidden reasoning, or scratchpad fields.

### Correlation, persistence, completion, reconstruction

ConversationService allocates `turn_id` before `session.ask()`. The completed trace uses the same turn, conversation, and session correlation IDs and receives both message IDs before the assistant insert. It is stored under `metadata.turn_trace` with `metadata.turn_trace_status == "completed"` in the same SQLite assistant-message insert.

The existing message retrieval path is the reconstruction seam. A reader can deserialize assistant metadata and reconstruct:

`input -> resolution -> routing/actions -> evidence -> final answer`.

Durable analytical memory is persisted only after the traced assistant message succeeds.

### Failure behavior

Trace construction and JSON serialization occur before persisting the model answer. If trace construction, serialization, or the assistant message write containing the trace fails, ConversationService raises `TurnTracePersistenceError`. The HTTP surface returns a safe 503 `trace_persistence_failed` response.

The model answer is neither returned nor persisted as a successful assistant message. The already-persisted user message remains visible as a failed attempt. This failure is not caught by a best-effort/title-generation path and cannot disappear silently. A2 does not introduce a second trace store.

### Retry and optional collection failures

The persisted user message carries a pending turn identity in its metadata before the runtime call. If mandatory assistant-message/TurnTrace persistence fails, a retry of the same pending user message reuses that turn ID and the existing user message rather than appending another user turn. The retry may re-run the runtime; its successful assistant trace identifies the original user message and turn ID. A retry with a different message creates a distinct turn. This is a narrow idempotency seam in the existing workspace metadata, not a generalized request framework.

Collection of an optional trace field (for example code version, table extraction, optional model usage, or a malformed optional action-trace detail) is best-effort: it records an explicit field-collection error or omits only that field and continues. Failure to construct, serialize, or durably persist the required TurnTrace envelope is mandatory and is the only trace condition mapped to `503 trace_persistence_failed`.

## Resolution contract

Every public trace outcome has this shape:

```json
{
  "status": "resolved | ambiguous | unknown",
  "canonical_value": "optional canonical value",
  "method": "catalog | entity_resolver | action_argument | evidence_fact | unavailable",
  "reason_code": "optional stable diagnostic",
  "evidence": {},
  "candidates": []
}
```

Internal diagnostics remain preserved. Entity `not_found` becomes public `unknown` with `reason_code: "not_found"`; `low_confidence` becomes `unknown` with `reason_code: "low_confidence"`; ambiguity remains `ambiguous` and retains candidates. Resolved values retain match method/evidence.

Metric and period use existing catalog/action/evidence information, not new resolver frameworks. Unknown values use specific codes such as `not_requested`, `not_observed`, or `unavailable_in_runtime`. A2 does not infer a missing value from prior turns. Ambiguous Apoquindo follows the existing clarification path.

## Routing, evidence, and validation boundaries

Routing derives from actual loop trajectory: clarification, semantic rejection, validated synthesis, legacy finalization, or model terminal. Action records derive from `ToolCall` and existing `ToolResult.trace`; arguments are allowlisted. SQL/tables appear only when existing metadata supplies them. A2 neither expands free-form SQL nor claims A3 result validation passed. A5 scores/cost analytics are deferred.

## db_chat transition boundary

Known in-repository callers are the Flask `/api/chat` route, `chat_bubble.js` loaded by factsheet output, legacy tests, and benchmark/eval adapters intentionally measuring the old surface. Its unique capabilities are provider fallback, legacy client-history protocol, and chart markdown rendering. They are not canonical Analyst dependencies.

Retirement requires evidence of zero non-test route callers or an explicit external migration decision; the bubble no longer load-bearing; unique capabilities superseded or deliberately excluded; and IDs 13--17 retired with code or no longer architecture debt. A2 documents the disposition without deleting the route or repairing transition debt to reduce the allowlist.

## Acceptance

Tests must run a real ConversationService plus runtime session with a scripted transport and temporary workspace DB. They prove trace persistence/completion/correlation/reconstruction, visible failure closure, no hidden-reasoning fields, traced actions/evidence, resolution diagnostics, ambiguity/unknown closure, and no db_chat dependency.

Run the exact baseline-gated CI command from `.github/workflows/eval-foundation.yml`, then `eval/benchmark/tests`, then `eval/product_alpha/tests`, each separately. IDs 1/12 may leave the allowlist only after a replacement explicit-contract test proves their old assertion stale and their node IDs pass. IDs 2, 6/7/9/10/11, and 8 remain out of A2; IDs 13--17 receive the documented transition disposition.

## Non-goals

No JLL cutover/migrations, Inciti, reports/artifacts, A3 SQL AST/result validation, A4 inheritance/corrections/topic reset, A5 judges/dashboards/OpenTelemetry, db_chat feature work, or PT gastos_usuario business-rule changes.
