import asyncio
from types import SimpleNamespace

import pytest

from app.llm.contracts import LLMResponse, Message, Usage
from app.llm.errors import ProviderDisabledError, ProviderHTTPError
from app.services.expert_team.service import provider_reasoner


class Provider:
    name='hy4-go-zero'
    def __init__(self,error=None): self.calls=0;self.active=0;self.peak=0;self.error=error
    async def complete(self,request):
        self.calls+=1;self.active+=1;self.peak=max(self.peak,self.active)
        await asyncio.sleep(0)
        self.active-=1
        if self.error: raise self.error
        return LLMResponse(Message('assistant','Respuesta válida con evidencia.'),Usage(1,1,2),'hy4-flash-free',self.name)


def test_experts_hy4_serial_and_three_attempt_cap():
    p=Provider();reason=provider_reasoner(p)
    async def run(): return await asyncio.gather(*(reason('synthetic','public fixture',100,'test') for _ in range(5)),return_exceptions=True)
    result=asyncio.run(run())
    assert p.calls==3 and p.peak==1
    assert sum(isinstance(r,ProviderDisabledError) for r in result)==2


@pytest.mark.parametrize('error',[ProviderHTTPError('hy4',429),ProviderHTTPError('hy4',402),ProviderDisabledError('cost')])
def test_expert_cut_latches_before_next_attempt(error):
    p=Provider(error);reason=provider_reasoner(p)
    async def run():
        with pytest.raises(type(error)): await reason('synthetic','public fixture',100,'test')
        with pytest.raises(ProviderDisabledError): await reason('synthetic','public fixture',100,'test')
    asyncio.run(run());assert p.calls==1


def test_hy4_records_no_heuristic_spend(monkeypatch):
    from app.services.budget import BudgetController
    recorded=[]
    monkeypatch.setattr(BudgetController,'can_spend',lambda self,db,amount:amount==0)
    monkeypatch.setattr(BudgetController,'record',lambda self,db,model,task,cost,tokens,**kw:recorded.append(cost))
    reason=provider_reasoner(Provider(),db=SimpleNamespace(commit=lambda:None))
    assert asyncio.run(reason('synthetic','public fixture',100,'test'))
    assert recorded==[0]


def test_non_hy4_keeps_existing_provider_and_budget_behavior(monkeypatch):
    from app.services.budget import BudgetController, BudgetExceededError
    p=Provider();p.name='other'
    reason=provider_reasoner(p)
    assert asyncio.run(reason('synthetic','fixture',100,'test'))
    monkeypatch.setattr(BudgetController,'can_spend',lambda *args:False)
    with pytest.raises(BudgetExceededError):
        asyncio.run(provider_reasoner(p,db=object())('synthetic','fixture',100,'test'))


def test_flag_route_resolves_factory_and_noncommitting_usage(monkeypatch):
    from app.llm import factory
    from app.services.budget import BudgetController
    p=Provider();monkeypatch.setenv('HY4_REPLACE_DEEPSEEK','1')
    monkeypatch.setattr(factory,'create_llm_provider',lambda:p)
    monkeypatch.setattr(BudgetController,'can_spend',lambda *args:True)
    monkeypatch.setattr(BudgetController,'record',lambda *args,**kw:None)
    seen=[]
    db=SimpleNamespace(flush=lambda:seen.append('flush'))
    reason=provider_reasoner(db=db,commit_usage=False)
    assert asyncio.run(reason('synthetic','fixture',100,'test'))
    assert seen==['flush']


def test_team_context_and_wrapper_paths(monkeypatch):
    from app.core import config
    from app.services.expert_team import service
    monkeypatch.setattr(config,'get_settings',lambda:SimpleNamespace(research_auth_required=True,is_production=False))
    with pytest.raises(RuntimeError): service.run_context(SimpleNamespace(info={}),ticker='TEST')
    monkeypatch.setattr(service,'holds_position',lambda *args:True)
    db=SimpleNamespace(info={'tenant_id':5,'user_id':'owner'})
    ctx=service.run_context(db,ticker=' test ',mode='chat',question='synthetic')
    assert ctx.ticker=='TEST' and ctx.holds_position
    monkeypatch.setattr(service,'default_experts',lambda:[])
    monkeypatch.setattr(service,'build_tools',lambda db:{})
    team=service.build_team(db,reasoner=provider_reasoner(Provider()))
    assert team.max_parallel==3
    async def run(context): return context
    fake=SimpleNamespace(run=run)
    monkeypatch.setattr(service,'build_team',lambda *args,**kwargs:fake)
    result=asyncio.run(service.run_team(db,ticker='TEST',total_timeout_s=4,judge_timeout_s=2))
    assert result.ticker=='TEST' and fake.total_timeout_s==4 and fake.judge_timeout_s==2


def test_holds_position_empty_and_missing(monkeypatch):
    from app.services.expert_team import service
    db=SimpleNamespace(scalars=lambda statement:SimpleNamespace(first=lambda:None))
    assert service.holds_position(db,5,'TEST') is False
    company=SimpleNamespace(id=1)
    values=iter([SimpleNamespace(first=lambda:company),SimpleNamespace(all=lambda:[0,1])])
    db=SimpleNamespace(scalars=lambda statement:next(values))
    assert service.holds_position(db,5,'TEST') is True
