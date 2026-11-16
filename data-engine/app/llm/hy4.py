"""Explicit, temporary Go promotion. No fallback, no default/global switch."""
from __future__ import annotations

import logging
import math
import threading
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

from app.llm.chat_provider import GoSubscriptionChatProvider
from app.llm.errors import ProviderDisabledError

MODEL = 'hy4-flash-free'
BASE = 'https://opencode.ai/inference/go/openai/v1'
CATALOG = 'https://opencode.ai/inference/go/v1/models'
NOTICE = 'Hy4 Flash bloqueado: no se pudo confirmar coste cero y facturación Go. No se usó otro modelo.'
_selected = ContextVar('hy4_explicit_chat_selection', default=False)
_lock = threading.Lock()
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
        if str(url) != BASE+'/chat/completions' or payload.get('model') != MODEL:
            raise ProviderDisabledError(NOTICE)
        return True
    return False


def zero(value):
    return type(value) in (int, float) and math.isfinite(value) and value == 0


def blocked():
    with _lock:
        return _blocked


def trip():
    global _blocked
    with _lock:
        _blocked = True
    logger.error('hy4_zero_cost_breaker_open: model disabled until operator review/restart')
    raise ProviderDisabledError(NOTICE)


class Hy4Provider(GoSubscriptionChatProvider):
    async def _complete(self, request, model):
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
