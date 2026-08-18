# Round B B10 Run Report

Fireworks / `accounts/fireworks/models/gpt-oss-120b` completed 15/15 Mini-Dev cases and 25 turns. Totals: 162,546 input, 6,550 output and 136,171 cached tokens; 90 SQL calls, 114 tool calls, 9,190.5 ms mean latency and 8,765.0 ms median latency. Four turns contain substantive final answers; 21 contain the tool-loop exhaustion sentinel.

Qualitative review pending: `tae-l1-008` was numerically accepted using `AVG(vacancia_pct)` over A/B/Total rows instead of selecting the consolidated Total row. This observation is retained for qualitative review; the grader was not changed during B10. Holdout was not executed.
