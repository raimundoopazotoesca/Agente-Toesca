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
 "type":"object","additionalProperties":False,"required":["fragments","canonical_metric_claims","governed_dataset_claims","derived_metric_claims"],"properties":{
 "fragments":{"type":"array","description":"The answer, in order. Insert a ref fragment wherever a governed figure belongs; the system renders it with the correct unit and scale, so do NOT also write that number inside a text fragment. NEVER write a computed number (a difference, a percent change, a percentage-point difference, a ratio) as a digit in a text fragment either -- use a derived_metric_ref instead; the system computes and renders it.","items":{"anyOf":[
  _TEXT_FRAGMENT,
  {"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"type":"string","const":"canonical_metric_ref"},"claim_id":{"type":"string","description":"claim_id of one canonical_metric_claims entry."}}},
  _RAW_TEXT_FRAGMENT,
  {"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"type":"string","const":"governed_dataset_ref"},"claim_id":{"type":"string","description":"claim_id of one governed_dataset_claims entry; renders the whole listing with its coverage caveat."}}},
  {"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"type":"string","const":"derived_metric_ref"},"claim_id":{"type":"string","description":"claim_id of one derived_metric_claims entry."}}}
 ]}},
 "canonical_metric_claims":{"type":"array","description":"One entry per individual governed figure cited. Each must reproduce EXACTLY one row returned by a governed tool: same metric_key, value, unit, entity_id and period, with evidence_id copied verbatim from that tool result's evidence_id field. Works both for a single-row result and for selecting one row out of a multi-row governed result.","items":{"type":"object","additionalProperties":False,"required":["claim_id","evidence_id","metric_key","value","unit","entity_id","period"],"properties":{"claim_id":{"type":"string"},"evidence_id":{"type":"string","description":"Verbatim evidence_id from the governed tool result."},"metric_key":{"type":"string"},"value":{"type":"number","description":"The raw value exactly as returned, unrounded and unconverted."},"unit":{"type":"string"},"entity_id":{"type":"string"},"period":{"type":"string"}}}},
 "governed_dataset_claims":{"type":"array","description":"One entry per governed multi-row result the answer relies on, including every enumeration of entities. Required whenever prose names two or more canonical assets of the same fund. Use metric_key and period null for a pure entity enumeration such as a fund's asset list.","items":{"type":"object","additionalProperties":False,"required":["claim_id","evidence_id","metric_key","entity_ids","period","universe_kind"],"properties":{"claim_id":{"type":"string"},"evidence_id":{"type":"string","description":"Verbatim evidence_id from the governed tool result."},"metric_key":{"type":["string","null"],"description":"Metric of the cited rows, or null when the result carries no metric."},"entity_ids":{"type":"array","items":{"type":"string"},"description":"Every entity relied on, exactly as returned by the tool."},"period":{"type":["string","null"],"description":"The ONE period shared by the cited rows, copied from them. Rows of different periods need one claim each. Use null only when the cited result carries no period at all."},"universe_kind":{"type":"string","description":"Copied from the tool result's coverage."}}}},
 "derived_metric_claims":{"type":"array","description":"One entry per computed quantity cited (a difference, a percent change, a percentage-point difference, a ratio between two canonical_metric_claims entries). The system computes the value deterministically from the two operands' raw values -- never write the computed number yourself anywhere.","items":{"type":"object","additionalProperties":False,"required":["claim_id","operation","lhs_claim_id","rhs_claim_id"],"properties":{"claim_id":{"type":"string"},"operation":{"type":"string","enum":["difference","percent_change","percentage_point_difference","ratio"],"description":"difference/percentage_point_difference = lhs - rhs. percent_change = (rhs - lhs) / lhs * 100, i.e. the change FROM lhs TO rhs. ratio = lhs / rhs."},"lhs_claim_id":{"type":"string","description":"claim_id of a canonical_metric_claims entry (the earlier/base value)."},"rhs_claim_id":{"type":"string","description":"claim_id of a canonical_metric_claims entry (the later/comparison value)."}}}}
 }}
