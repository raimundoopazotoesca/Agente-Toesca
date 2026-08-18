# Round B ? B11 Run Report

- Run ID: `round-b-20260817-b11`
- Code SHA: `unknown`
- Manifest SHA-256: `22a126062831c0d055142d6f1903b98e5baa68d0bc4c10861b83bf8bb4a3de4b`
- Mini-Dev canonical SHA-256: `unknown`
- Snapshot SHA-256: `unknown`
- Provider/model: `fireworks` / `accounts/fireworks/models/glm-5p2`
- Coverage: 15/15 cases; 25/25 turns completed.
- Holdout was not executed.

## Aggregate telemetry

| Metric | Value |
|---|---:|
| Turns recorded | 25 |
| Substantive final answers | 8 |
| Tool-loop exhausted | 17 |
| Input tokens | 357,045 |
| Output tokens | 18,246 |
| Cached tokens | 304,849 |
| Reasoning tokens persisted | 0 |
| SQL calls | 253 |
| Tool calls | 284 |
| Model rounds | 119 |
| Mean latency | 65,594.4 ms |
| Median latency | 52,469.0 ms |

`reasoning_content` is absent from both raw `turns.jsonl` and `events.jsonl`. The external raw archive was verified byte-identical file-by-file against the run directory.

## Deterministic grading

```json
{
  "completeness": {
    "mean": 0.428,
    "scored_turns": 25
  },
  "conversational_quality": {
    "mean": 0.25227272727272726,
    "scored_turns": 22
  },
  "factual_correctness": {
    "mean": 0.7714285714285715,
    "scored_turns": 7
  },
  "tool_correctness": {
    "mean": 0.375,
    "scored_turns": 4
  }
}
```

Limitations: deterministic grading does not replace qualitative judging; no global model score or production-readiness conclusion is made here.
