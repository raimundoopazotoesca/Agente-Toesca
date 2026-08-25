"""Structured synthesis envelope.

The schema is the ONLY place the model learns how claims bind to evidence, so
each field carries a description: a strict structured-output contract the
model cannot interpret correctly is indistinguishable from a model that
refuses to answer -- every turn fails closed. The descriptions are generic
(no metric, fund, asset or case-specific instruction); they describe the
binding contract the deterministic guards enforce.
"""

_TEXT_FRAGMENT = {
    "type": "object", "additionalProperties": False, "required": ["type", "text"],
    "properties": {
        "type": {"type": "string", "const": "text"},
        "text": {"type": "string", "description": "Prose. If it names two or more canonical assets of the same fund, those entities must all be listed in the entity_ids of some governed_dataset_claim, or the answer is rejected."},
    },
}
_RAW_TEXT_FRAGMENT = {
    "type": "object", "additionalProperties": False, "required": ["type", "text"],
    "properties": {
        "type": {"type": "string", "const": "raw_text"},
        "text": {"type": "string", "description": "Prose derived from raw exploration rather than a governed capability. Same entity-provenance rule as text."},
    },
}

SYNTHESIS_ENVELOPE_SCHEMA = {
 "type":"object","additionalProperties":False,"required":["fragments","canonical_metric_claims","governed_dataset_claims","derived_metric_claims","table_claims"],"properties":{
 "fragments":{"type":"array","description":"The answer, in order. Insert a ref fragment wherever a governed figure belongs; the system renders it with the correct unit and scale, so do NOT also write that number inside a text fragment. NEVER write a computed number (a difference, a percent change, a percentage-point difference, a ratio) as a digit in a text fragment either -- use a derived_metric_ref instead; the system computes and renders it. NEVER decide yourself which of two governed figures is greater, smaller, higher, lower, leads or ranks first -- use a derived_metric_ref with operation \"comparison\" instead; the system compares the real values and renders the correct relation phrase (\"es mayor que\"/\"es menor que\"/\"es igual a\"). When naming two or more entities from the same governed breakdown, use their real identity (a canonical_metric_ref/governed_dataset_ref, or the entity name already provided) -- never a vague placeholder like \"uno de los activos\"/\"el otro\"/\"el primero\".","items":{"anyOf":[
  _TEXT_FRAGMENT,
  {"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"type":"string","const":"canonical_metric_ref"},"claim_id":{"type":"string","description":"claim_id of one canonical_metric_claims entry."}}},
  _RAW_TEXT_FRAGMENT,
  {"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"type":"string","const":"governed_dataset_ref"},"claim_id":{"type":"string","description":"claim_id of one governed_dataset_claims entry; renders the whole listing with its coverage caveat."}}},
  {"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"type":"string","const":"derived_metric_ref"},"claim_id":{"type":"string","description":"claim_id of one derived_metric_claims entry."}}}
 ]}},
 "canonical_metric_claims":{"type":"array","description":"One entry per individual governed figure cited. Each must reproduce EXACTLY one row returned by a governed tool: same metric_key, value, unit, entity_id and period, with evidence_id copied verbatim from that tool result's evidence_id field. Works both for a single-row result and for selecting one row out of a multi-row governed result.","items":{"type":"object","additionalProperties":False,"required":["claim_id","evidence_id","metric_key","value","unit","entity_id","period"],"properties":{"claim_id":{"type":"string"},"evidence_id":{"type":"string","description":"Verbatim evidence_id from the governed tool result."},"metric_key":{"type":"string"},"value":{"type":"number","description":"The raw value exactly as returned, unrounded and unconverted."},"unit":{"type":"string"},"entity_id":{"type":"string"},"period":{"type":"string"}}}},
 "governed_dataset_claims":{"type":"array","description":"One entry per governed multi-row result the answer relies on, including every enumeration of entities. Required whenever prose names two or more canonical assets of the same fund. Use metric_key and period null for a pure entity enumeration such as a fund's asset list.","items":{"type":"object","additionalProperties":False,"required":["claim_id","evidence_id","metric_key","entity_ids","period","universe_kind"],"properties":{"claim_id":{"type":"string"},"evidence_id":{"type":"string","description":"Verbatim evidence_id from the governed tool result."},"metric_key":{"type":["string","null"],"description":"Metric of the cited rows, or null when the result carries no metric."},"entity_ids":{"type":"array","items":{"type":"string"},"description":"Every entity relied on, exactly as returned by the tool."},"period":{"type":["string","null"],"description":"The ONE period shared by the cited rows, copied from them. Rows of different periods need one claim each. Use null only when the cited result carries no period at all."},"universe_kind":{"type":"string","description":"Copied from the tool result's coverage."}}}},
 "derived_metric_claims":{"type":"array","description":"One entry per computed quantity OR qualitative relation cited (a difference, a percent change, a percentage-point difference, a ratio, or a greater/less/equal comparison between two canonical_metric_claims entries). The system computes the result deterministically from the two operands' raw values -- never write the computed number or decide the comparison direction yourself anywhere.","items":{"type":"object","additionalProperties":False,"required":["claim_id","operation","lhs_claim_id","rhs_claim_id"],"properties":{"claim_id":{"type":"string"},"operation":{"type":"string","enum":["difference","percent_change","percentage_point_difference","ratio","comparison"],"description":"difference/percentage_point_difference = lhs - rhs. percent_change = (rhs - lhs) / lhs * 100, i.e. the change FROM lhs TO rhs. ratio = lhs / rhs. comparison = renders whether lhs is greater than, less than, or equal to rhs -- use this for ANY \"which is higher/lower/leads\" claim instead of asserting it in free text."},"lhs_claim_id":{"type":"string","description":"claim_id of a canonical_metric_claims entry (the earlier/base value)."},"rhs_claim_id":{"type":"string","description":"claim_id of a canonical_metric_claims entry (the later/comparison value)."}}}},
 "table_claims":{"type":"array","description":"Optional: when several governed figures differ across two or more entities, periods or metrics, you MAY group their claim_ids here so the system renders a compact table instead of (or alongside) prose -- use your judgement about whether a table communicates this better than a sentence; a single fact never needs one. Leave this empty for a plain scalar answer. If the user explicitly asked for a table, populate this; if the user explicitly asked you not to use a table, leave it empty even if the data would otherwise support one. You never write table headers, cell values, row order or missing-data cells yourself -- the system derives all of that deterministically from the claims you cite here.","items":{"type":"object","additionalProperties":False,"required":["claim_id","cell_claim_ids","order_by"],"properties":{
  "claim_id":{"type":"string"},
  "cell_claim_ids":{"type":"array","items":{"type":"string"},"description":"claim_ids of already-cited canonical_metric_claims and/or derived_metric_claims entries (never governed_dataset_claims) to include as table cells, in any order. The system infers rows, columns, headers and row order from these claims' own entity/period/metric fields; a claim_id it cannot place unambiguously fails the whole answer, so cite only claims that truly form one coherent table (one shared set of varying dimensions)."},
  "order_by":{"type":["string","null"],"enum":["value_desc","value_asc",None],"description":"Only meaningful for a single-column ranking table (rows vary by entity, one metric, one period): sort rows by that value, highest or lowest first. Use null for every other shape, and null when row order doesn't represent a ranking."}
 }}}
 }}
