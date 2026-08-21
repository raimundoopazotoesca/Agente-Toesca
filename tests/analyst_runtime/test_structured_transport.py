from types import SimpleNamespace
from tools.analyst_runtime.session import OpenAIResponsesTransport
from tools.analyst_runtime.transport import ModelRequest, StructuredOutputContract
from tools.analyst_runtime.synthesis_schema import SYNTHESIS_ENVELOPE_SCHEMA

class R:
 def __init__(self,o): self.o=o; self.calls=[]
 def create(self,**kw): self.calls.append(kw); return self.o
class C:
 def __init__(self,o): self.responses=R(o)
def req(contract=None): return ModelRequest('s',[],'x',[],contract)
def test_structured_mapping_and_round_trip():
 out={'fragments':[{'type':'text','text':'x'}],'canonical_metric_claims':[]}; c=C(SimpleNamespace(output=[],output_text='',output_parsed=out,usage=None)); t=OpenAIResponsesTransport(c,'m',[])
 r=t.complete(req(StructuredOutputContract('SynthesisEnvelope',SYNTHESIS_ENVELOPE_SCHEMA,True)))
 assert r.structured_output==out; assert c.responses.calls[0]['text']['format']=={'type':'json_schema','name':'SynthesisEnvelope','schema':SYNTHESIS_ENVELOPE_SCHEMA,'strict':True}; assert c.responses.calls[0]['tools']==[]
def test_plain_request_has_no_format():
 c=C(SimpleNamespace(output=[],output_text='ok',usage=None)); OpenAIResponsesTransport(c,'m',[]).complete(req()); assert 'text' not in c.responses.calls[0]
def test_missing_structured_output_fails_closed():
 c=C(SimpleNamespace(output=[],output_text='',usage=None));
 try: OpenAIResponsesTransport(c,'m',[]).complete(req(StructuredOutputContract('x',{},True)))
 except ValueError as e: assert str(e)=='structured_output_required'
 else: assert False
