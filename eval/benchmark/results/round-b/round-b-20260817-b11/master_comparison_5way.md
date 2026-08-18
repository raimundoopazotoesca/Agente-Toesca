# Round B ? Five-candidate Quantitative Comparison

Computed exclusively from valid raw run artifacts. Deterministic dimensions are mean score with number of scored turns in parentheses; `?` means not deterministically scored. No global score or winner is inferred.

| Provider/model | Coverage | Substantive | Exhausted | Completeness | Factual | Conversational | Tool correctness | Input | Output | Cached | Reasoning | SQL | Tools | Rounds | Mean latency | Median latency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dashscope / qwen3.8-max | 15/15 cases; 25/25 turns | 3 | 22 | 0.320 (25) | 1.000 (3) | 0.091 (22) | 0.400 (4) | 338,156 | 19,667 | 279,552 | 0 | 256 | 270 | 123 | 55077.0 ms | 50765.0 ms |
| sambanova / MiniMax-M2.7 | 15/15 cases; 25/25 turns | 7 | 18 | 0.372 (25) | 0.667 (6) | 0.209 (22) | 0.375 (4) | 234,638 | 10,133 | 106,496 | 0 | 157 | 227 | 117 | 10873.7 ms | 10125.0 ms |
| mistral / mistral-large-2512 | 15/15 cases; 25/25 turns | 11 | 14 | 0.240 (25) | 0.125 (8) | 0.261 (23) | 0.333 (3) | 241,414 | 12,960 | 44,432 | 0 | 138 | 275 | 100 | 53335.1 ms | 27984.0 ms |
| fireworks / accounts/fireworks/models/gpt-oss-120b | 15/15 cases; 25/25 turns | 4 | 21 | 0.320 (25) | 0.600 (5) | 0.130 (23) | 0.267 (6) | 162,546 | 6,550 | 136,171 | 0 | 90 | 114 | 118 | 9190.5 ms | 8765.0 ms |
| fireworks / accounts/fireworks/models/glm-5p2 | 15/15 cases; 25/25 turns | 8 | 17 | 0.428 (25) | 0.771 (7) | 0.252 (22) | 0.375 (4) | 357,045 | 18,246 | 304,849 | 0 | 253 | 284 | 119 | 65594.4 ms | 52469.0 ms |

Substantive final answer: a non-empty final answer other than the tool-loop-exhausted sentinel.
