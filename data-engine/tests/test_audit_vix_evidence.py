import asyncio
import json
from types import SimpleNamespace

from app.llm import LLMResponse, Message
from app.llm.contracts import Usage
from app.schemas import ChatResponse, SynthesisSection
from app.services.chat_synthesis_service import SECTION_ORDER, ChatSynthesisService


def test_macro_opinion_cannot_become_company_fact_with_reused_citation(monkeypatch):
    from app.services import chat_synthesis_service as target
    monkeypatch.setattr(target,'reader_context',lambda _: {'third_party_heuristic':{'claimed_levels':{'above':50},'verification':'unverified_opinion'}}, raising=False)
    from app.services.budget import BudgetController
    monkeypatch.setattr(BudgetController,'can_spend',lambda *a:True)
    monkeypatch.setattr(BudgetController,'record',lambda *a:None)
    sections=[SynthesisSection(key=k,body='Ingresos observados de Microsoft',citations=['financial_fact:1'] if k in {'facts','calculations'} else []) for k in SECTION_ORDER]
    baseline=ChatResponse(answer='Ingresos observados de Microsoft',sources=[{'type':'financial_fact','id':1,'text':'Ingresos de Microsoft 10'}],sections=sections)
    output={'sections':[{'key':k,'body':'VIX superior a 50 confirma una oportunidad de compra probada para Microsoft.' if k=='facts' else 'Sin información adicional.', 'citations':['financial_fact:1'] if k in {'facts','calculations'} else []}for k in SECTION_ORDER], 'answer':'La oportunidad de compra está verificada por los datos de la empresa.', 'confidence':0.9,'insufficient_data':False}
    class Provider:
        name='test'
        async def complete(self, request):
            return LLMResponse(message=Message('assistant',json.dumps(output)),usage=Usage(input_tokens=1,output_tokens=1,total_tokens=2),model='test-model',provider='test')
    result=asyncio.run(ChatSynthesisService(Provider()).synthesize(question='Analiza Microsoft',ticker='MSFT',baseline=baseline,db=SimpleNamespace()))
    assert result.model=='deterministic', (result.model,result.sections[0],result.llm_trace)
