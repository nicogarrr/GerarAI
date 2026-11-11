"""Zero real calls. Mutations of destination/model/context cannot open billing."""
import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.adapters import OpenAICompatibleProvider
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import ProviderDisabledError
from app.llm.factory import create_llm_provider
from app.llm.chat_provider import create_chat_llm_provider, create_background_llm_provider
from app.llm.thesis_go import create_thesis_narrative_provider
from app.llm.free_interactive import create_free_interactive_provider
from app.llm.tenant_config import TenantLLMConfig, tenant_llm_config_scope
from app.llm.free_only import free_only_tenant_scope

FACTORIES = [create_llm_provider, create_chat_llm_provider, create_background_llm_provider,
             create_thesis_narrative_provider, create_free_interactive_provider]


def settings(**kw):
    return Settings(app_env='test', llm_free_only=True, llm_free_only_exempt_tenant_ids='7',
                    opencode_go_api_key='platform-test', thesis_go_enabled=True,
                    thesis_go_api_key='paid-test', chat_go_subscription_enabled=True, **kw)


@pytest.mark.parametrize('factory', FACTORIES)
@pytest.mark.parametrize('byok', [False, True])
def test_all_factories_pin_to_platform_free_even_with_byok(factory, byok, monkeypatch):
    cfg = settings()
    monkeypatch.setattr('app.core.config.get_settings', lambda: cfg)
    sent = []
    def handler(req):
        sent.append(req)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    custom = TenantLLMConfig(provider='openai', base_url='https://api.openai.com/v1', model='gpt-4.1', api_key='byok') if byok else None
    with free_only_tenant_scope(8), tenant_llm_config_scope(custom):
        provider = factory(cfg, client=client)
        asyncio.run(provider.complete(LLMRequest([Message('user', 'hello')], task='chat')))
    assert len(sent) == 1
    assert str(sent[0].url) == 'https://opencode.ai/zen/v1/chat/completions'
    assert json.loads(sent[0].content)['model'] == 'deepseek-v4.1-flash-free'
    assert sent[0].headers['authorization'] == 'Bearer platform-test'


@pytest.mark.parametrize('url,model', [
    ('https://opencode.ai/zen/go/v1/chat/completions', 'deepseek-v4.1-flash'),
    ('https://api.openai.com/v1/chat/completions', 'gpt-4.1'),
    ('https://opencode.ai/zen/v1/chat/completions', 'deepseek-v4.1-flash'),
    ('http://opencode.ai/zen/v1/chat/completions', 'deepseek-v4.1-flash-free'),
    ('https://opencode.ai.evil.test/zen/v1/chat/completions', 'deepseek-v4.1-flash-free'),
    ('https://opencode.ai/zen/v1/chat/completions?paid=1', 'deepseek-v4.1-flash-free'),
])
def test_direct_adapter_bypass_is_blocked_before_transport(url, model, monkeypatch):
    monkeypatch.setattr('app.core.config.get_settings', lambda: settings())
    sent = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: sent.append(req)))
    provider = OpenAICompatibleProvider(api_key='k', base_url='https://x.test', default_model=model, client=client)
    with free_only_tenant_scope(8), pytest.raises(ProviderDisabledError):
        asyncio.run(provider._send(url, headers={}, payload={'model': model}))
    assert not sent


@pytest.mark.parametrize('tenant', [None, True, 0, -1, '7'])
def test_missing_or_unverified_tenant_never_calls_even_free(tenant, monkeypatch):
    monkeypatch.setattr('app.core.config.get_settings', lambda: settings())
    with free_only_tenant_scope(tenant), pytest.raises(ProviderDisabledError):
        asyncio.run(create_llm_provider(settings()).complete(LLMRequest([Message('user', 'hello')])) )


def test_exempt_verified_internal_tenant_and_flag_off_preserve_existing_path():
    with free_only_tenant_scope(7):
        assert create_thesis_narrative_provider(settings()).name == 'opencode-go'
    cfg = settings().model_copy(update={'llm_free_only': False})
    with free_only_tenant_scope(8):
        assert create_thesis_narrative_provider(cfg).name == 'opencode-go'


def test_jev_paid_microdecisions_blocked_without_post(monkeypatch):
    from app.llm.jev import JevDecisionClient
    monkeypatch.setattr('app.core.config.get_settings', lambda: settings())
    sent = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: sent.append(req)))
    with free_only_tenant_scope(8), pytest.raises(ProviderDisabledError):
        asyncio.run(JevDecisionClient('k', client=client).systemone({}, {}))
    assert not sent


def test_scope_restores_and_bridge_copies_identity():
    from app.llm.free_only import restricted
    from app.services.async_bridge import run_from_any_context
    cfg = settings()
    async def read():
        return restricted(cfg)
    async def bridge():
        return run_from_any_context(read())
    assert restricted(cfg)
    with free_only_tenant_scope(7):
        assert not asyncio.run(bridge())
        with free_only_tenant_scope(8):
            assert asyncio.run(bridge())
        assert not restricted(cfg)
    assert restricted(cfg)


def test_http_dependency_binds_internal_id_and_resets(monkeypatch):
    from types import SimpleNamespace
    from app.services.tenant_llm_settings_service import bind_tenant_llm_settings
    from app.llm.free_only import restricted
    monkeypatch.setattr('app.services.tenant_llm_settings_service.load_config_for_tenant', lambda *_: None)
    async def exercise():
        dep = bind_tenant_llm_settings(SimpleNamespace(info={'tenant_id': 7}))
        await anext(dep)
        assert not restricted(settings())
        await dep.aclose()
        assert restricted(settings())
    asyncio.run(exercise())


def test_worker_binds_internal_id_then_cleans_after_success_and_skip(monkeypatch):
    from types import SimpleNamespace
    from app.workers.tenant_llm_middleware import TenantLLMSettingsMiddleware
    from app.llm.free_only import restricted
    monkeypatch.setattr('app.services.tenant_llm_settings_service.load_config_for_tenant', lambda *_: None)
    middleware = TenantLLMSettingsMiddleware()
    for cleanup in (middleware.after_process_message, middleware.after_skip_message):
        msg = SimpleNamespace(kwargs={'tenant_id': 7}, options={})
        middleware.before_process_message(None, msg)
        assert not restricted(settings())
        cleanup(None, msg)
        assert restricted(settings())
        assert not msg.options


def test_no_free_key_and_master_disable_do_not_call(monkeypatch):
    for change in ({'llm_enabled': False}, {'opencode_go_api_key': None}, {'llm_provider': 'disabled'}):
        cfg = settings().model_copy(update=change)
        with free_only_tenant_scope(8):
            assert create_llm_provider(cfg).name == 'disabled'


def test_free_destination_is_not_overridden_by_paid_env(monkeypatch):
    cfg = settings(opencode_free_base_url='https://paid.test/v1', opencode_free_model='paid-model', llm_model_overrides={'chat': 'paid'})
    with free_only_tenant_scope(8):
        provider = create_llm_provider(cfg)
        assert provider._base_url == 'https://opencode.ai/zen/v1'
        assert provider.model_router.resolve(LLMRequest([Message('user', 'hello')], task='chat')) == 'deepseek-v4.1-flash-free'


def test_payload_tenant_and_model_alias_cannot_claim_exemption(monkeypatch):
    from app.llm.free_only import enforce_free_only
    monkeypatch.setattr('app.core.config.get_settings', lambda: settings())
    with free_only_tenant_scope(8), pytest.raises(ProviderDisabledError):
        enforce_free_only('https://api.openai.com/v1/chat/completions', {'model': 'gpt-4.1', 'tenant_id': 7, 'admin': True})


def test_early_guard_rejects_non_mapping_payload_and_missing_tenant():
    from app.llm.free_only import enforce_free_only, FREE_ENDPOINT
    with free_only_tenant_scope(8), pytest.raises(ProviderDisabledError):
        enforce_free_only(FREE_ENDPOINT, None, settings())
    with free_only_tenant_scope(None), pytest.raises(ProviderDisabledError):
        enforce_free_only(FREE_ENDPOINT, {'model': 'deepseek-v4.1-flash-free'}, settings())


def test_opt_out_and_verified_exemption_do_not_block_transport():
    from app.llm.free_only import enforce_free_only
    cfg = settings()
    with free_only_tenant_scope(7):
        enforce_free_only('https://paid.test', {'model': 'paid'}, cfg)
    enforce_free_only('https://paid.test', {}, cfg.model_copy(update={'llm_free_only': False}))
