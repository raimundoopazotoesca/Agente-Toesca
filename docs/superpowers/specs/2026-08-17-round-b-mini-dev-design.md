# Round B Mini-Dev B1 Design

## Scope

Implement a reproducible, deterministic-grading-only execution of the frozen
`toesca-analyst-mini-dev-v1` on Track B. The frozen YAML, its content hash,
the Dev cases, prompts, semantic context and tool schema remain immutable.

## Inference configuration

`InferenceProfile` is an immutable value injected into `TrackBFrontier` and
then each Track B session. It owns only request parameters and a profile name;
it does not alter the prompt, SQL loop, session history, or tool schema.

`B1_STANDARD` is an explicit registry keyed by provider and exact requested
model. All five entries omit `temperature`, `top_p`, and `seed`. Groq/
`openai/gpt-oss-120b` explicitly sends `reasoning_effort="medium"`. NVIDIA,
DashScope, Mistral and SambaNova send no reasoning override. No profile uses
`high` or `max`; an unsupported explicit Groq parameter is an adapter/protocol
failure, not a reason to silently change configuration.

## Execution and evidence

A dedicated Round B runner loads the frozen manifest and Dev cases in their
declared order. It creates one Track B adapter per candidate and one new
session per case. It records every returned turn and deterministic grading
result, with judge-only dimensions explicitly marked `not_scored_yet`.

Per-turn evidence includes requested/resolved provider/model, model rounds,
tool calls, sandbox-captured SQL, usage fields reported by the provider,
latency, retry count, error taxonomy and cost when the pricing table supplies
compatible token prices. Reasoning content is never retained.

The runner retries once only for 429, 5xx, network and timeout errors,
honouring a numeric Retry-After header when supplied. It has no semantic retry,
cross-model fallback, key fallback, prompt change or routing.

## Run manifest

Before network execution the runner writes a separate JSON manifest. It pins
the Mini-Dev ID and canonical content hash, already-committed code SHA, Track
B, snapshot identity, system/context and tool-schema hashes, B1 profile,
provider configuration, limits, retry/timeout policy, grader implementation
hashes, judge status and execution date. Its own SHA-256 is stored alongside
the run results; it never changes Mini-Dev identity.

## Testing

Offline tests cover profile lookup and omission/pass-through request mapping,
usage extraction without invented values, cost accounting, manifest identity,
order/turn-count enforcement, retry taxonomy, and deterministic output shape.
Existing Track B, freeze, sandbox and deterministic-grader tests remain the
regression suite required before any live call.
