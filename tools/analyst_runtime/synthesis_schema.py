SYNTHESIS_ENVELOPE_SCHEMA = {
 "type":"object","additionalProperties":False,"required":["fragments","canonical_metric_claims"],"properties":{
 "fragments":{"type":"array","items":{"oneOf":[
  {"type":"object","additionalProperties":False,"required":["type","text"],"properties":{"type":{"const":"text"},"text":{"type":"string"}}},
  {"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"const":"canonical_metric_ref"},"claim_id":{"type":"string"}}},
  {"type":"object","additionalProperties":False,"required":["type","text"],"properties":{"type":{"const":"raw_text"},"text":{"type":"string"}}}
 ]}},
 "canonical_metric_claims":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["claim_id","evidence_id","metric_key","value","unit","entity_id","period"],"properties":{"claim_id":{"type":"string"},"evidence_id":{"type":"string"},"metric_key":{"type":"string"},"value":{"type":"number"},"unit":{"type":"string"},"entity_id":{"type":"string"},"period":{"type":"string"}}}}
 }}
