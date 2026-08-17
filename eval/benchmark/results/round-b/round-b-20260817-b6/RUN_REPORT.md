# Round B B6 Run Report

- Run ID: `round-b-20260817-b6`
- Code SHA: `3107d4b147cae32f8b2b77b37a1e422bd8547559`
- Manifest SHA256: `75ee51861aa0e89258a8eb7c0a97d1edaa257adf207a152fa75bfc8d7143ec95`
- Mini-Dev canonical hash: `df8cd68c690266e770210e752ab8078ef8f3dc23b175e55abe97963a18d3558f`
- Snapshot SHA256: `592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c`

DashScope/Qwen and SambaNova/MiniMax completed 15/15 cases and 25 turns each. Mistral completed one case then encountered 429/rate-limit. Groq and NVIDIA were not executed in B6. Aggregated latency, tokens, SQL and tool calls are in `metrics.json`; deterministic evidence is in the blind comparison.

`turns_recorded` counts persisted turn records. `substantive_final_answers` excludes the exact tool-loop sentinel `(no se alcanzo una respuesta final dentro del limite de iteraciones de herramientas)`: Qwen 3/25; MiniMax 7/25. The versioned v2 mapping aligns X with MiniMax and Y with Qwen; the immutable cache mapping is retained as historical evidence of the prior label swap.

The blind qualitative review was fixed before revealing `qualitative_mapping_v2.json`: Qwen is the provisional qualitative winner and MiniMax the operational winner. Neither is production-ready. Provider 429s are provider-tier/coverage limits, not evidence of model incapacity. Holdout remains sealed and was never executed.
