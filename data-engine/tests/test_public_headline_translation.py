import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import public_headline_translation as service


class Provider:
    name = 'fake'
    def __init__(self, text='Apple anuncia resultados 2026'):
        self.text = text
        self.calls = 0
    async def complete(self, request):
        self.calls += 1
        assert request.metadata['tenant_id'] == '1'
        assert 'untrusted DATA' in request.messages[0].content
        return SimpleNamespace(text=json.dumps({'text':self.text}),degraded=False,warnings=())

@pytest.fixture(autouse=True)
def clear(monkeypatch):
    service._cache.clear()
    monkeypatch.setattr(service,'reserve_quota',lambda *a,**k:{'allowed':True})


def test_cache_tenant_and_original():
    async def run():
        db=SimpleNamespace(info={'tenant_id':1})
        p=Provider()
        one=await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p)
        two=await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p)
        assert one==two and one['status']=='translated' and p.calls==1
        assert one['original']=='Apple reports earnings 2026'
        db.info['tenant_id']=2
        assert (await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p))['status']=='unavailable'
        assert p.calls==2
    asyncio.run(run())


def test_bad_output_cooldown_and_quota(monkeypatch):
    async def run():
        db=SimpleNamespace(info={'tenant_id':1})
        p=Provider('Apple anuncia resultados 2027')
        assert (await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p))['status']=='unavailable'
        await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p)
        assert p.calls==1
        monkeypatch.setattr(service,'reserve_quota',lambda *a,**k:{'allowed':False})
        await service.translate_external_headline(db,'Apple reports results',provider=p)
        assert p.calls==1
    asyncio.run(run())


def test_free_provider_never_uses_cascade_or_paid_override(monkeypatch):
    from app.core.config import Settings
    settings=Settings(llm_provider='cascade',opencode_go_model='deepseek-v4.1-flash-free',llm_model_overrides={'x':'paid'},opencode_go_fallback_model='paid')
    monkeypatch.setattr(service,'get_settings',lambda:settings)
    captured=[]
    monkeypatch.setattr(service,'create_llm_provider',lambda value:captured.append(value) or Provider())
    assert service.free_provider()[0].name=='fake'
    assert captured[0].llm_provider=='opencode-go'
    assert captured[0].llm_model_overrides=={} and captured[0].opencode_go_fallback_model==''
    monkeypatch.setattr(service,'_resolved_verified_free_model',lambda _:None)
    assert service.free_provider()==(None,None)


def test_spanish_skips_and_unscoped_denied():
    async def run():
        p=Provider()
        assert (await service.translate_external_headline(SimpleNamespace(info={'tenant_id':1}),'La empresa anuncia resultados',provider=p))['status']=='not_needed'
        assert p.calls==0
        with pytest.raises(PermissionError):
            await service.translate_external_headline(SimpleNamespace(info={}), 'Apple reports earnings',provider=p)
    asyncio.run(run())


class ChainProvider:
    """Proveedor de cadena: falla o devuelve salida controlada, y registra el orden."""

    def __init__(self, name, behavior):
        self.name = name
        self.behavior = behavior
        self.calls = []

    async def complete(self, request):
        self.calls.append(request.model)
        if self.behavior == 'raise':
            raise RuntimeError('provider down')
        if self.behavior == 'bad_numbers':
            return SimpleNamespace(text=json.dumps({'text': 'Apple anuncia resultados 2027'}), degraded=False, warnings=())
        return SimpleNamespace(text=json.dumps({'text': 'Apple anuncia resultados 2026'}), degraded=False, warnings=())


def test_chain_order_first_valid_wins(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        opencode = ChainProvider('opencode-go', 'raise')
        groq = ChainProvider('groq', 'ok')
        gemini = ChainProvider('gemini', 'ok')
        monkeypatch.setattr(service, 'free_provider_chain',
                            lambda: [(opencode, 'deepseek-v4.1-flash-free'), (groq, 'openai/gpt-oss-120b'), (gemini, 'gemini-3.5-flash-lite')])
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        assert result['status'] == 'translated' and result['text'] == 'Apple anuncia resultados 2026'
        # OpenCode falló, Groq ganó: Gemini ni se llama.
        assert opencode.calls == ['deepseek-v4.1-flash-free']
        assert groq.calls == ['openai/gpt-oss-120b']
        assert gemini.calls == []
    asyncio.run(run())


def test_chain_all_fail_returns_unavailable_never_invented(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        chain = [(ChainProvider('opencode-go', 'raise'), 'm1'),
                 (ChainProvider('groq', 'raise'), 'm2'),
                 (ChainProvider('gemini', 'raise'), 'm3')]
        monkeypatch.setattr(service, 'free_provider_chain', lambda: chain)
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        assert result['status'] == 'unavailable' and result['text'] is None
        assert result['original'] == 'Apple reports earnings 2026'
        assert all(p.calls for p, _ in chain)
    asyncio.run(run())


def test_chain_invalid_output_falls_through(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        bad = ChainProvider('opencode-go', 'bad_numbers')
        good = ChainProvider('groq', 'ok')
        monkeypatch.setattr(service, 'free_provider_chain', lambda: [(bad, 'm1'), (good, 'm2')])
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        # Cifra cambiada por el primero (2027): se rechaza y gana el segundo.
        assert result['status'] == 'translated' and result['text'] == 'Apple anuncia resultados 2026'
        assert bad.calls == ['m1'] and good.calls == ['m2']
    asyncio.run(run())


def test_chain_empty_is_unavailable(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        monkeypatch.setattr(service, 'free_provider_chain', lambda: [])
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        assert result['status'] == 'unavailable' and result['text'] is None
    asyncio.run(run())
