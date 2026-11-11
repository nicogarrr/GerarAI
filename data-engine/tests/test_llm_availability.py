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
