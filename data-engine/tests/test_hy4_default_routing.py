import pytest

from app.core.config import Settings
from app.llm import hy4
from app.llm.chat_provider import create_background_llm_provider, create_chat_llm_provider
from app.llm.factory import create_llm_provider
from app.llm.free_interactive import create_free_interactive_provider
from app.llm.free_only import free_only_provider
from app.llm.tenant_config import TenantLLMConfig, tenant_llm_config_scope
from app.llm.thesis_go import create_thesis_narrative_provider

FACTORIES=[create_llm_provider,create_chat_llm_provider,create_background_llm_provider,
           create_free_interactive_provider,create_thesis_narrative_provider,free_only_provider]


@pytest.mark.parametrize('factory',FACTORIES)
@pytest.mark.parametrize('old',['deepseek-v4.1-flash','deepseek-v4.1-flash-free'])
def test_pilot_switch_replaces_deepseek_without_any_fallback(monkeypatch,factory,old):
    monkeypatch.setenv('HY4_REPLACE_DEEPSEEK','1')
    cfg=Settings(app_env='test',llm_free_only=True,opencode_go_api_key='synthetic',opencode_go_model=old,
                 thesis_go_model=old,opencode_go_fallback_model='paid-never',gemini_chat_fallback_enabled=True)
    provider=factory(cfg)
    assert isinstance(provider,hy4.Hy4Provider)
    assert provider._base_url==hy4.BASE and provider._fallback_model is None and provider._max_retries==0


def test_replacement_scope_ignores_non_deepseek_and_non_go_tenant(monkeypatch):
    cfg=Settings(app_env='test',opencode_go_api_key='synthetic')
    monkeypatch.delenv('HY4_REPLACE_DEEPSEEK',raising=False)
    assert hy4.replacement_provider(cfg) is None
    monkeypatch.setenv('HY4_REPLACE_DEEPSEEK','1')
    assert hy4.replacement_provider(cfg,model='other') is None
    with tenant_llm_config_scope(TenantLLMConfig(provider='openai',base_url='https://api.openai.com/v1',model='deepseek-v4.1-flash',api_key='synthetic')):
        assert hy4.replacement_provider(cfg) is None
    with tenant_llm_config_scope(TenantLLMConfig(provider='opencode-go',base_url='https://opencode.ai/zen/go/v1',model='deepseek-v4.1-flash',api_key='synthetic')):
        assert isinstance(hy4.replacement_provider(cfg),hy4.Hy4Provider)
    disabled=cfg.model_copy(update={'llm_provider':'disabled'})
    assert hy4.replacement_provider(disabled) is None


@pytest.mark.parametrize('reason', ['timeout','cooling','ProviderHTTPError429','ProviderHTTPError503',
    'ProviderHTTPError401','ProviderHTTPError','ProviderTransportErrorConnect','_LanguageRejected',
    'ProviderResponseErrorEmpty','other'])
def test_existing_failure_reasons_are_nonempty_bilingual(reason):
    from app.llm.chat_provider import _reason_en, _reason_es
    assert _reason_en(reason) and _reason_es(reason)


def test_cache_eviction_is_best_effort():
    import asyncio
    from types import SimpleNamespace

    from app.llm.chat_provider import _evict_rejected
    async def broken(response): raise RuntimeError('synthetic')
    async def ok(response): return None
    async def run():
        await _evict_rejected(SimpleNamespace(evict_cached=ok), SimpleNamespace(cache_key=None))
        await _evict_rejected(SimpleNamespace(evict_cached=broken), SimpleNamespace(cache_key='synthetic'))
        await _evict_rejected(SimpleNamespace(evict_cached=ok), SimpleNamespace(cache_key='synthetic'))
    asyncio.run(run())


def test_promotion_ceiling_never_restores_paid_deepseek(monkeypatch):
    monkeypatch.setenv('HY4_REPLACE_DEEPSEEK','1')
    monkeypatch.setattr(hy4,'promotion_ended',lambda:True)
    cfg=Settings(app_env='test',opencode_go_api_key='synthetic')
    for factory in FACTORIES:
        provider=factory(cfg)
        assert provider.name=='disabled'
