# A3 Post-A3.3 Gap Register

**Status of this document**: engineering register, not a bug tracker and not marketing.
It records findings from the post-A3.3 conversational benchmark analysis, and is
deliberately explicit about which findings are reproduced facts versus hypotheses.

**Scope boundary**: this document does not implement anything. It classifies four gaps
(A–D) surfaced by conversational benchmark analysis and states, per gap, whether it is
implementation scope now, needs reproduction, or is deferred. See
`docs/CURRENT_STATE.md` for the closed status of A3.1/A3.2/A3.3 and the current
protected HEAD (`58cb06bc832e35a01a713d22219e6947853c03ff`).

## Principles

- Not every benchmark finding is a confirmed bug. A finding is "confirmed" only when
  backed by a reproduced trace, not by re-reading the transcript of a single run.
- "Incorrect answer" and "absence of data" are different failure modes and must not be
  conflated. Governance requires the agent to say "No existe información para esta
  consulta" when the DB genuinely lacks data — but that same sentence is a **failure**,
  not correct behavior, if the data exists and retrieval broke somewhere between entity
  resolution and query execution. Gap C exists specifically to force that distinction.
- Architectural risk (a structural gap that would explain a class of failures) is not
  the same claim as a reproduced regression. Both are recorded here, but labeled
  differently.
- No gap in this register is grounds to reopen A3.3. A3.3's deterministic trend-direction
  validation is closed and out of scope for any change proposed here.
- Conversation State v2 (referenced by Gaps A and D) is a future initiative. Nothing in
  this document authorizes starting it now.
- Cross-cutting recommendation: the benchmark/eval suite should evolve to measure
  state-transition correctness (deixis resolution, entity-set carryover) as **grader
  metadata on existing cases**, not necessarily as a new top-level eval dimension —
  that design choice is itself deferred, not decided here.

## Gap A — Deixis / Conversation State

**ID**: GAP-A

**Description**: A user turn referring back to an implicit entity via natural-language
deixis — e.g. "Compara el NOI de **el activo actual** con Apoquindo..." — requires the
runtime to resolve "el activo actual" to a specific entity from prior conversational
context rather than from the current turn's explicit text.

**Benchmark case(s)**: "Compara el NOI de el activo actual con Apoquindo..." (conversational
benchmark, entity-carryover class).

**Evidence available**: Source-level only, no trace evidence. Confirmed by reading code:

- The runtime is **not stateless**: `tools/analyst_workspace/conversation_service.py`
  maintains an `AnalystSession`, and `tools/analyst_runtime/analyst_loop.py` receives
  explicit turn history — durable analytical context exists.
- However, that durable context is built around **evidence and claims**
  (`evidence_inventory.py`, the A3.2 evidence-projection contract), not around an
  explicit structured conversational-entity state. There is no `current_entity`,
  `current_metric`, or `current_period` field maintained across turns.
- `Conversation.context` (in `tools/analyst_workspace/store.py`) is a generic container,
  not a typed entity-tracking structure.

**Classification**: **parcialmente confirmado / design risk.**
The absence of an explicit entity-state structure is confirmed by reading the code. Whether
this absence actually causes an incorrect answer in a live turn is **not** confirmed — no
trace exists showing the resolver failing on this exact case. Do not present this as a
reproduced bug.

**Diagnóstico técnico**: The runtime has durable context but it is evidence-shaped, not
entity-shaped. Deictic resolution ("el activo actual") would need to fall back to whatever
general-purpose entity resolution exists in `tools/analyst_runtime/resolution.py`, which is
not designed around conversational carryover — it resolves entities within a turn, not across
turns.

**Riesgo**: Medium. If unresolved, deictic references silently resolve to the wrong entity
or fail resolution, and — depending on how the failure surfaces — could produce either a
wrong answer or a false "no data" response (see Gap C for why that distinction matters).

**Recomendación**: Reproduce with a full trace (`turn_trace.py` output) on the exact
benchmark case; measure the actual state transition attempted, not just the final answer.
Only after reproduction should a design memo for Conversation State v2 be scoped.

**Scope actual**: **investigar/reproducir.** Not implement now.

**Dependencias futuras**: Depends on the same underlying design question as Gap D
(entity-set state) — should be reproduced and, if pursued, designed together as part of a
single future Conversation State v2 memo, not solved gap-by-gap.

---

## Gap B — Synthesis / Comparison Completeness

**ID**: GAP-B

**Description**: In a multi-entity comparison ("Apoquindo vs PT 2025"), an earlier analysis
pass observed apparent malformation or content loss during the synthesis/finalization step
that composes the final answer from claims and evidence.

**Benchmark case(s)**: Apoquindo vs PT 2025 (conversational benchmark, comparison class).

**Evidence available**: A prior analysis noted the symptom qualitatively; **no reproduced
trace or regression test exists for this repo state.** A3.2 and A3.3 protect numeric claims
and trend direction specifically (`coverage_guard.py`, `trend_assertions.py`), but neither
was designed to validate completeness of broader prose conclusions in a synthesis step —
that is a different failure surface than either guard covers.

**Classification**: **plausible / no demostrado.**
Do not assert this as a reproduced defect. The existence of a separate finalization/synthesis
phase (`synthesis_schema.py`) that composes claims into prose is confirmed; that this phase
drops or malforms content in the specific benchmark case is not confirmed against the current
HEAD.

**Diagnóstico técnico**: A3.2/A3.3 close the gap for numeric values and trend direction
specifically. Neither guard validates structural or semantic completeness of the synthesized
comparison as a whole (e.g., "does the final answer actually address both entities the user
asked to compare"). This is a plausible residual gap in coverage, not a demonstrated failure.

**Riesgo**: Medium if real — comparison questions are a common query shape — but severity
cannot be assessed responsibly without reproduction; a single prior observation is not
sufficient evidence of frequency or magnitude.

**Recomendación**: Build a targeted regression test for the Apoquindo vs PT 2025 case (or an
equivalent minimal repro), capture full trace/trajectory, and measure completeness explicitly
(e.g., did the synthesis step reference evidence for every entity requested). Do not modify
A3.3 as part of this investigation — trend-direction validation is a separate, closed concern.

**Scope actual**: **investigar/reproducir.**

**Dependencias futuras**: None beyond building the regression test; independent of Gaps A/C/D.

---

## Gap C — Retrieval / Apo4501

**ID**: GAP-C

**Description**: A prior analysis flagged Apoquindo 4501 ("Apo4501") as a case where the
agent appeared to report missing data. That prior analysis reports that direct inspection
found the asset exists with substantial data:

- Apo4501 exists as a canonical asset belonging to the Apo fund.
- ER data exists for that asset.
- A direct query is reported to have found approximately 715 rows, spanning 2019-01 to
  2026-05.

**Benchmark case(s)**: Apoquindo 4501 queries (conversational benchmark, retrieval class).

**Evidence available**: **Reported evidence, not independently reproduced as part of this
consolidation.** The "~715 rows, 2019-01 to 2026-05" figure is stated by the prior analysis
that produced this gap; this consolidation pass did not re-run that query against any
database (live or version-controlled snapshot) to confirm it, and the prior analysis itself
does not state which database instance or snapshot the query ran against. Do not treat the
row count as a canonically verified fact until it is reproduced with its data source stated
explicitly. This gap must **not** be resolved by running that query against the live,
uncommitted `memory/agente_toesca_v2.db` as a shortcut — see the reproduction steps below,
which call for a full trace, not a one-off row count. **No trace evidence yet showing
where, in the resolution chain, the agent's answer diverged from the reported ground
truth.**

**Classification**: **no reproducido / retrieval failure potencial.**
This must **not** be prematurely classified as "missing data" on the strength of the
reported evidence above — but that reported evidence is itself unreproduced by this
consolidation (see "Evidence available"), so this is not yet classified as a confirmed
retrieval bug either. Two things need reproduction before this gap can move out of
"no reproducido": (1) the underlying row count/date range itself, with its data source
stated, and (2) the specific point of failure in the chain (user → entity resolution →
tool selection → tool args → query → result).

**Diagnóstico técnico**: The failure, if the reported data presence holds up under
reproduction, is somewhere in:

```
user → entity resolution → tool selection → tool args → query → result
```

If the underlying data is confirmed present on reproduction, a report of "no data" for
this case would be a **retrieval failure**, not a true data-absence case. Candidate failure
points:
entity resolution not mapping "Apo4501"/"Apoquindo 4501" phrasing to the canonical asset key,
tool selection choosing a scope that excludes this asset, or tool arguments (date range,
fund filter) narrowing the query incorrectly.

**Riesgo**: **High** specifically because of the governance rule this interacts with: the
agent is required to say "No existe información para esta consulta" when data is genuinely
absent. If this exact phrase is being produced by a retrieval failure rather than genuine
absence, every such response is a **false negative** that looks identical to correct
governed behavior on the surface — this is the highest-risk gap in this register precisely
because it is silent by design.

**Recomendación**: Reproduce with a full trace on an Apo4501 query, against a stated,
recorded database instance/snapshot (so the row-count claim itself becomes verifiable, not
just the retrieval-chain question). Verify, in order: (0) re-run the underlying data-presence
check and record which DB instance/snapshot it ran against; (1) entity resolution output for
"Apo4501" / "Apoquindo 4501" phrasing, (2) which tool was selected and why, (3) the exact
arguments passed to that tool, (4) the raw query executed, (5) the raw result before
presentation. Explicitly distinguish "query correctly returned zero rows for the requested
scope" from "query never reached the right scope."

**Scope actual**: **investigar/reproducir** — highest priority of the four gaps given the
false-negative risk against the "no data" governance rule.

**Dependencias futuras**: None architecturally; this is a reproduction task, not a design
task. May inform Gap A if the root cause turns out to be entity-resolution/deixis-related.

---

## Gap D — Enumeration → Deixis / Entity Set

**ID**: GAP-D

**Description**: A query that enumerates multiple entities ("PT" → 3 activos) followed by a
deictic follow-up over that whole set ("valor de los activos", "tasaciones de esos activos")
requires the runtime to retain and resolve a **set** of entities, not a single current
entity.

**Benchmark case(s)**: PT → 3 activos → "valor de los activos" → "tasaciones de esos activos"
(conversational benchmark, entity-set/enumeration class).

**Evidence available**: Source-level, confirmed by reading the persistence and runtime
layers:

- Workspace persistence (`tools/analyst_workspace/store.py`,
  `conversation_service.py`) is generic — it stores conversation/message history and
  evidence-shaped durable context, as established for Gap A.
- There is **no structured state for an entity set** anywhere in the runtime or workspace
  layers. A single "current entity" representation, even if it existed, would not be
  sufficient here — "esos activos" refers to a set produced by a prior enumeration, not
  one entity.

**Classification**: **confirmado como limitación arquitectónica.**
Unlike Gaps A–C, this is not contingent on trace reproduction to establish the structural
absence — the absence of any entity-set state is directly verifiable by reading
`tools/analyst_workspace/store.py` and `tools/analyst_runtime/resolution.py`. What is not
yet measured is the frequency/severity of user turns that depend on this capability.

**Riesgo**: Medium-high for any pilot usage pattern that enumerates then refers back
("cuáles son los activos de PT" → "sus tasaciones") — this is a natural, common
conversational pattern for portfolio-level questions.

**Recomendación**: Scope a future **Conversation State v2 design memo** that explicitly
models:

- `current_entity`
- `entity_set`
- `current_fund`
- `current_metric`
- `current_period`

and add deterministic tests for deictic references over both single entities and sets. This
should be designed together with Gap A, not as two separate efforts.

**Scope actual**: **deferred.** Confirmed as a real architectural gap, but explicitly **not**
implementation scope in this checkpoint — this document registers it, it does not schedule it.

**Dependencias futuras**: Depends on / should be unified with Gap A's investigation.
Both feed a single future Conversation State v2 design memo, out of scope for this sync.

---

## Summary table

| Gap | Description | Classification | Scope now |
|---|---|---|---|
| A | Deixis over a single implicit entity ("el activo actual") | Parcialmente confirmado / design risk | Investigar/reproducir |
| B | Synthesis/comparison completeness across entities | Plausible / no demostrado | Investigar/reproducir |
| C | Apo4501 retrieval vs. true data absence | No reproducido / retrieval failure potencial | Investigar/reproducir (highest priority) |
| D | Deixis over an enumerated entity set ("esos activos") | Confirmado como limitación arquitectónica | Deferred (Conversation State v2) |

None of the above is implementation scope in this checkpoint. A3.3 remains closed and is not
reopened by any finding in this register.
