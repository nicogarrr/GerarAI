"""Transport-level zero-billing policy. Identity comes only from trusted binding."""
from contextlib import contextmanager
from contextvars import ContextVar

FREE_ENDPOINT = 'https://opencode.ai/zen/v1/chat/completions'
FREE_MODEL = 'deepseek-v4.1-flash-free'
_tenant = ContextVar('free_only_verified_internal_tenant', default=None)


def set_free_only_tenant(tenant):
    return _tenant.set(tenant if type(tenant) is int and tenant > 0 else None)


def reset_free_only_tenant(token):
    _tenant.reset(token)


@contextmanager
def free_only_tenant_scope(tenant):
    token = set_free_only_tenant(tenant)
    try:
        yield
    finally:
        reset_free_only_tenant(token)


def restricted(settings=None):
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings()
    if not settings.llm_free_only:
        return False
    tenant = _tenant.get()
    exemptions = {int(part.strip()) for part in settings.llm_free_only_exempt_tenant_ids.split(',')
                  if part.strip().isascii() and part.strip().isdigit() and int(part.strip()) > 0}
    return tenant is None or tenant not in exemptions


def enforce_free_only(url, payload, settings=None):
    from app.llm.errors import ProviderDisabledError
    if not restricted(settings):
        return
    if _tenant.get() is None:
        raise ProviderDisabledError('llm_free_only_verified_tenant_required')
    if str(url) != FREE_ENDPOINT or not isinstance(payload, dict) or payload.get('model') != FREE_MODEL:
        raise ProviderDisabledError('llm_free_only_destination_or_model_blocked')


def free_only_provider(settings, client=None):
    """Only platform free, no BYOK, user overrides, fallback or paid helper."""
    from app.llm.adapters import DisabledProvider
    if _tenant.get() is None:
        return DisabledProvider('llm_free_only_verified_tenant_required')
    if not settings.llm_enabled or settings.llm_provider == 'disabled':
        return DisabledProvider('disabled_by_configuration')
    if not (settings.opencode_go_api_key and settings.opencode_go_api_key.strip()):
        return DisabledProvider('llm_free_only_key_not_configured')
    from app.llm.chat_provider import GoSubscriptionChatProvider
    from app.llm.factory import _pin_to_model
    return GoSubscriptionChatProvider(
        api_key=settings.opencode_go_api_key, base_url='https://opencode.ai/zen/v1',
        default_model=FREE_MODEL, provider_name='opencode-free',
        model_overrides=_pin_to_model(FREE_MODEL), max_retries=0,
        timeout_seconds=15, total_timeout_seconds=18, max_output_tokens=4000,
        extra_headers={'x-opencode-session': settings.opencode_go_session, 'User-Agent': 'GerarAI-free-only/1.0'},
        reasoning_effort='low', reasoning_effort_models={FREE_MODEL}, client=client,
    )
