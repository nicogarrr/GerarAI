from app.core.config import Settings
from app.llm.free_only import free_only_tenant_scope
from app.services.llm_availability import availability


def cfg(**kw):
    return Settings(app_env='test', llm_free_only=True, opencode_go_api_key='test', **kw)


def test_snapshot_has_no_network_and_does_not_claim_verified_quota():
    with free_only_tenant_scope(8):
        out = availability('chat', cfg())
    assert out['state'] == 'unverified'
    assert out['can_start'] is True
    assert out['reason'] == 'not_probed'
    assert 'test' not in str(out)


def test_open_payment_breaker_disables_action_for_matching_key_only(monkeypatch):
    import time
    from app.llm import base
    key = ('opencode-free', 'deepseek-v4.1-flash-free', base._credential_fingerprint({'Authorization': 'Bearer test'}))
    monkeypatch.setitem(base._payment_required_breaker, key, time.monotonic() + 60)
    with free_only_tenant_scope(8):
        out = availability('thesis', cfg())
        other = availability('chat', cfg().model_copy(update={'opencode_go_api_key': 'other'}))
    assert out['state'] == 'paused' and not out['can_start']
    assert 0 < out['retry_after_seconds'] <= 60
    assert out['reason'] == 'payment'
    assert other['can_start']


def test_disabled_and_missing_context_never_offer_ai():
    with free_only_tenant_scope(None):
        assert not availability('analysis', cfg())['can_start']
    with free_only_tenant_scope(8):
        assert availability('analysis', cfg(llm_enabled=False))['state'] == 'off'


def test_all_features_observe_free_quota_breaker(monkeypatch):
    import time
    from app.llm import base
    key = ('opencode-free', 'deepseek-v4.1-flash-free', base._credential_fingerprint({'Authorization': 'Bearer test'}))
    monkeypatch.setitem(base._free_quota_breaker, key, time.monotonic() + 40)
    with free_only_tenant_scope(8):
        for feature in ('chat', 'analysis', 'thesis', 'debate'):
            out = availability(feature, cfg())
            assert not out['can_start'] and out['state'] == 'paused'


def test_composite_is_degraded_when_only_primary_is_blocked(monkeypatch):
    import time
    from app.llm import base
    from app.llm.chat_provider import GO_SUBSCRIPTION_PROVIDER
    s = Settings(app_env='test', llm_free_only=False, opencode_go_api_key='test', chat_go_subscription_enabled=True,
                 opencode_free_chat_fallback_enabled=True)
    key = (GO_SUBSCRIPTION_PROVIDER, 'deepseek-v4.1-flash', base._credential_fingerprint({'Authorization': 'Bearer test'}))
    monkeypatch.setitem(base._payment_required_breaker, key, time.monotonic() + 50)
    out = availability('chat', s)
    assert out['state'] == 'degraded' and out['can_start']


def test_api_adapter_requires_tenant_and_only_reads_local_snapshot(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException
    from app.api.routes.settings import get_llm_availability
    monkeypatch.setattr('app.services.llm_availability.availability', lambda feature: {'feature': feature, 'can_start': False})
    assert get_llm_availability('chat', SimpleNamespace(info={'tenant_id': 8}))['feature'] == 'chat'
    with pytest.raises(HTTPException):
        get_llm_availability('chat', SimpleNamespace(info={}))


def _block(monkeypatch, provider, model):
    import time
    from app.llm import base
    key = (provider.name, model, base._credential_fingerprint({'Authorization': f'Bearer {provider._api_key}'}))
    monkeypatch.setitem(base._payment_required_breaker, key, time.monotonic() + 60)


def test_internal_adapter_fallback_is_still_available_and_really_completes(monkeypatch):
    import asyncio
    import httpx
    from app.llm.factory import create_llm_provider
    from app.llm.contracts import LLMRequest, Message
    s = Settings(app_env='test', opencode_go_api_key='test', opencode_go_model='deepseek-v4.1-flash-free',
                 opencode_go_fallback_model='space-bunny-free', llm_free_only=False)
    called = []
    def respond(req):
        import json
        called.append(json.loads(req.content)['model'])
        return httpx.Response(200, json={'choices':[{'message':{'content':'local fallback'},'finish_reason':'stop'}],
                                        'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
    p = create_llm_provider(s, client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    _block(monkeypatch, p, 'deepseek-v4.1-flash-free')
    assert availability('analysis', s)['can_start']
    assert availability('analysis', s)['state'] == 'degraded'
    assert asyncio.run(p.complete(LLMRequest([Message('user','hello')], task='main_financial_analysis'))).text == 'local fallback'
    assert called == ['space-bunny-free']
    _block(monkeypatch, p, 'space-bunny-free')
    assert not availability('analysis', s)['can_start']


def test_explicit_models_on_shared_backup_instance_are_not_deduplicated(monkeypatch):
    from app.llm.adapters import OpenAICompatibleProvider
    from app.llm.chat_provider import ChatFallbackProvider
    p = OpenAICompatibleProvider(api_key='test', base_url='https://local.test', default_model='main', provider_name='test', model_overrides={'chat': 'main'})
    shared = OpenAICompatibleProvider(api_key='test', base_url='https://local.test', default_model='unused', provider_name='test')
    chain = ChatFallbackProvider(p, shared, backup_model='backup-one', extra_backups=((shared, 'backup-two'),))
    monkeypatch.setattr('app.llm.chat_provider.create_chat_llm_provider', lambda _: chain)
    _block(monkeypatch, p, 'main')
    _block(monkeypatch, shared, 'backup-one')
    out = availability('chat', Settings(app_env='test'))
    assert out['can_start'] and out['state'] == 'degraded'
    _block(monkeypatch, shared, 'backup-two')
    assert not availability('chat', Settings(app_env='test'))['can_start']


def test_gemini_two_models_and_router_override_are_real_candidates():
    from app.llm.adapters import OpenAICompatibleProvider
    from app.llm.chat_provider import ChatFallbackProvider, GEMINI_MODELS, SequentialFallbackProvider
    from app.llm.cascade import CascadeProvider
    from app.llm.contracts import LLMRequest, Message
    from app.services.llm_availability import _candidates
    req = LLMRequest([Message('user', 'local')], task='chat')
    def provider(name):
        return OpenAICompatibleProvider(api_key='test', base_url='https://local.test', default_model=name,
                                        provider_name='test', model_overrides={'chat':name, 'alias':'resolved'})
    primary, backup, gemini = provider('main'), provider('backup'), provider('gemini-default')
    chain = ChatFallbackProvider(primary, backup, backup_model='alias', backup2=gemini,
                                 extra_backups=((gemini,GEMINI_MODELS[1]),))
    assert [(p, m) for p,m in _candidates(chain,req)] == [(primary,'main'),(backup,'resolved'),(gemini,GEMINI_MODELS[0]),(gemini,GEMINI_MODELS[1])]
    sequence = SequentialFallbackProvider(primary, backup, gemini, backup_models=('alias',), backup2_models=GEMINI_MODELS)
    assert _candidates(sequence,req) == _candidates(chain,req)
    assert _candidates(CascadeProvider((primary,backup)),req) == [(primary,'main'),(backup,'backup')]


def test_suppressed_internal_fallback_does_not_add_nonexistent_route():
    from app.llm.adapters import OpenAICompatibleProvider
    from app.llm.contracts import LLMRequest, Message
    from app.services.llm_availability import _candidates
    p = OpenAICompatibleProvider(api_key='test',base_url='https://local.test',default_model='main',
                                 model_overrides={'chat':'main','alias':'main'},fallback_model='alias')
    assert _candidates(p, LLMRequest([Message('user','local')],task='chat')) == [(p,'main')]


def test_factory_failure_is_off_not_a_promise(monkeypatch):
    def broken(_):
        raise ValueError('invalid configuration')
    monkeypatch.setattr('app.llm.factory.create_llm_provider', broken)
    assert availability('analysis', cfg())['state'] == 'off'
