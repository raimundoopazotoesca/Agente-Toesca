# Account concept mapping inventory v1

Reproducible with `python -X utf8 -m tools.analytics.account_mapping_inventory --output docs/account-concept-mapping-inventory-v1.md`. The command opens the database read-only.

| Concept | Source codes | Status | Semantics |
|---|---|---|---|
| property_tax | PT_CONTRIB, APO_CONTRIB, INMOSA_CONTRIB, SUCDEN_CONTRIB, 3-1-40-102 | MAPPED | Expense magnitude; UF is read from legacy `monto_clp` where stated in YAML. |
| property_tax_surtax | 3-1-40-119 | MAPPED | CLP expense magnitude. |
| insurance | PT_SEG, APO3001_SEG, INMOSA_SEG, SUCDEN_SEG, 3-1-40-100 | MAPPED | Expense magnitude; coverage remains NONE where a given asset has no governed mapping/rows. |
| common_expenses | PT_GC_VAC, APO_GC_VAC | MAPPED | Legacy UF expense magnitude. |
| administration_fees | PT_ADM, APO_ADM, INMOSA_ADM, 3-1-10-102, 3-1-10-105 | MAPPED | Exact-code mappings only. |
| maintenance_repairs | INMOSA_PROV_REP | PARTIAL | Only this source has a validated v1 mapping. |
| APO3001_CONTRIB_SOBRETASA | combined contribution/surtax | AMBIGUOUS | Excluded from totals: no governed split is present. |

Concepts not currently supported by validated mappings: financial interest expenses and operational utilities. Historical rows with NULL codes are not mapped unless an exact, scoped source-name mapping is added to the catalog.
