# Toesca Analyst Benchmark Dev Set v1.1 freeze

Supersedes Dev Set v1 only for the factual, reproducible correction in
`tce-investigationmultidomain-001`: `proximo_vencimiento_tri` now resolves
to the scalar year `2028` (one row, one column). Case selection, prompts,
order, snapshot and rubric are unchanged.

- Dataset correction commit: `6c0dd57ec3b6e2268943f1e86323ba49d767383e`
- Snapshot SHA256: `592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c`
- Mini-Dev canonical manifest SHA256: `df8cd68c690266e770210e752ab8078ef8f3dc23b175e55abe97963a18d3558f`
- Validation: 39 Mini-Dev ground-truth refs resolve to exactly one row and one column.
