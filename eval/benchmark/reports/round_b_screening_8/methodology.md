# Methodology

The package is produced solely from the validated external archive. Candidate labels are a reproducible shuffle with seed `20260818`; selection is metadata-derived, never archive order. The evaluator receives no provider, model, run, candidate, cost, token, latency, source-path, or hidden-reasoning data.

Each candidate has 25 Mini-Dev turns across 15 cases. Assessment is qualitative over the visible answer, SQL/tool trace, case facts, forbidden claims, and deterministic grading. It prioritizes correctness, grounding, scope/entity control, investigation, uncertainty, decision usefulness, and stopping. It does not reward answer length, tool volume, or answer rate alone.

Candidate evidence from B12 is valid for capability/quality review, but its retry reliability is not strictly comparable because it predates the change disabling Anthropic SDK internal retries. Opus 5 is excluded: incomplete after repeated Anthropic 529 overloaded responses.
