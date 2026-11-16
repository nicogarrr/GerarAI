"""Explicit, temporary Go promotion. No fallback, no default/global switch."""
from __future__ import annotations

import logging
import math
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn

import httpx

from app.llm.chat_provider import GoSubscriptionChatProvider
from app.llm.errors import ProviderDisabledError

MODEL = 'hy4-flash-free'
BASE = 'https://opencode.ai/inference/go/openai/v1'
CATALOG = 'https://opencode.ai/inference/go/v1/models'
NOTICE = 'Hy4 Flash bloqueado: no se pudo confirmar coste cero y facturación Go. No se usó otro modelo.'
_selected = ContextVar('hy4_explicit_chat_selection', default=False)
_lock = threading.Lock()
_admission = threading.Lock()
_blocked = False
logger = logging.getLogger(__name__)


@contextmanager
def selection_scope(enabled):
    token = _selected.set(bool(enabled))
    try:
        yield
    finally:
        _selected.reset(token)


def enforce_destination(url, payload):
    if _selected.get():
        if blocked() or str(url) != BASE+'/chat/completions' or payload.get('model') != MODEL:
            raise ProviderDisabledError(NOTICE)
        return True
    return False


def zero(value):
    return type(value) in (int, float) and math.isfinite(value) and value == 0


def blocked():
    with _lock:
        return _blocked


def trip() -> NoReturn:
    global _blocked
    with _lock:
        _blocked = True
    logger.error('hy4_zero_cost_breaker_open: model disabled until operator review/restart')
    raise ProviderDisabledError(NOTICE)


class Hy4Provider(GoSubscriptionChatProvider):
    async def _complete(self, request, model):
        # One admitted inference per process. Do not queue catalog checks
        # behind in-flight requests or let them pass after a circuit trip.
        if not _admission.acquire(blocking=False):
            raise ProviderDisabledError('Hy4 ocupado; no se ha usado otro modelo.')
        try:
            # Workers have no HTTP scope. Apply the destination/model guard
            # ONLY to this admitted provider call, never unrelated work.
            with selection_scope(True):
                return await self._complete_guarded(request, model)
        finally:
            _admission.release()

    async def _complete_guarded(self, request, model):
        if blocked() or model != MODEL:
            raise ProviderDisabledError(NOTICE)
        # Read current price before EVERY inference. Metadata arriving after
        # inference cannot undo a first charge if the provider changes price.
        try:
            if self._client is not None:
                response = await self._client.get(CATALOG, timeout=8)
            else:
                async with httpx.AsyncClient(timeout=8) as client:
                    response = await client.get(CATALOG)
            response.raise_for_status()
            models = response.json()['data']
            entry = next(item for item in models if item.get('id') == MODEL)
            if entry['api']['chat-completions']['base_url'] != BASE:
                trip()
            prices = entry['cost']['text']
            if not zero(prices['input']['price']) or not zero(prices['output']['price']):
                trip()
        except ProviderDisabledError:
            raise
        except Exception:
            # No stale catalog or guessed-free suffix is an authorization.
            trip()
        # Another request may have tripped while this catalog GET awaited.
        # Never let an earlier successful preflight reopen the circuit.
        if blocked():
            raise ProviderDisabledError(NOTICE)
        return await super()._complete(request, model)

    def _response_json(self, response):
        body = super()._response_json(response)
        usage = body.get('usage')
        if not isinstance(usage, dict):
            trip()
        go = usage.get('opencode')
        if not isinstance(go, dict):
            trip()
        if (body.get('model') != MODEL or not zero(usage.get('cost'))
                or go.get('billing_source') != 'go' or not zero(go.get('list_cost'))
                or not zero(go.get('allowance'))):
            trip()
        return body


def create_hy4_provider(settings, client=None):
    if not settings.llm_enabled or settings.llm_provider == 'disabled' or not settings.opencode_go_api_key:
        raise ProviderDisabledError(NOTICE)
    from app.llm.factory import _pin_to_model
    return Hy4Provider(api_key=settings.opencode_go_api_key, base_url=BASE,
        default_model=MODEL, provider_name='hy4-go-zero', model_overrides=_pin_to_model(MODEL),
        fallback_model=None, max_retries=0, timeout_seconds=18, total_timeout_seconds=24,
        max_output_tokens=4000, reasoning_effort='none', reasoning_effort_models={MODEL},
        extra_headers={'User-Agent': 'GerarAI-brain/1.0', 'x-opencode-session': settings.opencode_go_session},
        client=client)


def promotion_ended():
    # Operational 14-day ceiling from the owner's Nov 16 11:56 Madrid request,
    # NOT a claim about the provider's unconfirmed contractual end time.
    from datetime import UTC, datetime
    return datetime.now(UTC) >= datetime(2026, 11, 30, 10, 56, tzinfo=UTC)


def replacement_provider(settings, client=None, *, model=None):
    """Deployment switch, never an unrestricted free-model registry entry.

    Pilot enables HY4_REPLACE_DEEPSEEK=1 after exact-SHA review. A missing or
    repriced promotion stays closed; there is no automatic paid restoration.
    """
    import os
    if os.environ.get('HY4_REPLACE_DEEPSEEK', '').strip() != '1':
        return None
    from app.llm.tenant_config import current_tenant_llm_config
    tenant = current_tenant_llm_config()
    # Never replace a tenant-owned configuration or its credentials.
    if tenant is not None or not settings.llm_enabled:
        return None
    candidate = model or settings.opencode_go_model
    if candidate not in {'deepseek-v4.1-flash', 'deepseek-v4.1-flash-free', MODEL}:
        return None
    if settings.llm_provider not in {'auto', 'opencode', 'opencode_go', 'opencode-go', 'cascade'}:
        return None
    if promotion_ended():
        from app.llm.adapters import DisabledProvider
        return DisabledProvider('hy4_promotion_window_ended_no_paid_restore')
    return create_hy4_provider(settings, client)
