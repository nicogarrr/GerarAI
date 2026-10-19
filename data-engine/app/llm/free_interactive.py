"""Bounded OpenCode -> confirmed-no-billing AI Studio debate chain."""
from __future__ import annotations

import logging

import httpx

from app.core.config import Settings, get_settings
from app.llm.cascade import _FALL_THROUGH, CascadeProvider
from app.llm.chat_provider import GEMINI_MODELS, _gemini_backup
from app.llm.contracts import LLMRequest
from app.llm.errors import LLMError, ProviderHTTPError, ProviderResponseError, ProviderTransportError
from app.llm.factory import _opencode_go, _pin_to_model
from app.llm.model_aliases import VERIFIED_FREE_MODELS

logger = logging.getLogger(__name__)


class FreeLLMUnavailable(LLMError):
    def __init__(self, *, quota: bool = False):
        self.quota = quota
        super().__init__("LLM gratuito agotado, vuelve más tarde" if quota else
                         "LLM gratuito no disponible, vuelve más tarde")


class FreeInteractiveProvider(CascadeProvider):
    async def _run(self, request: LLMRequest):
        failures = []
        for member in self.members:
            try:
                response = await member.complete(request)
                if response.degraded:
                    raise ProviderResponseError("truncated or degraded debate response")
                return response
            except _FALL_THROUGH as exc:
                failures.append(exc)
                logger.warning("Free debate member %s failed: %s",
                               member.model_router.resolve(request), type(exc).__name__)
        raise FreeLLMUnavailable(quota=all(
            isinstance(exc, ProviderHTTPError) and exc.status_code == 429
            for exc in failures
        ))

    async def complete(self, request: LLMRequest):
        try:
            return await super().complete(request)
        except ProviderTransportError:
            raise FreeLLMUnavailable() from None


def create_free_interactive_provider(settings: Settings | None = None, *, client: httpx.AsyncClient | None = None):
    settings = settings or get_settings()
    if not settings.llm_enabled or settings.llm_provider == "disabled" or not settings.opencode_go_api_key:
        raise FreeLLMUnavailable()
    # Never use the generic Gemini/OpenRouter cascade: keys may carry billing.
    # Ignore paid environment overrides rather than silently widening cost scope.
    configured = (settings.opencode_go_model, settings.opencode_go_fallback_model)
    models = list(dict.fromkeys([m for m in configured if m in VERIFIED_FREE_MODELS]
                               + ["deepseek-v4.1-flash-free", "space-bunny-free"]))
    members = []
    for model in models:
        pinned = settings.model_copy(update={
            "opencode_go_model": model, "opencode_go_fallback_model": "",
            "llm_model_overrides": _pin_to_model(model),
        })
        members.append(_opencode_go(pinned, client=client, max_retries=0,
                                    timeout_seconds=12, total_timeout_seconds=14,
                                    reasoning_effort="low"))
    for member in members:
        member.interactive_quota_breaker = True
    # AI Studio is free only with confirmed no billing, not merely by model ID.
    # Reuse the existing guard; never add Gemini to the OpenCode free registry.
    if settings.gemini_chat_fallback_enabled:
        for model in GEMINI_MODELS:
            gemini = _gemini_backup(settings, client, timeout_seconds=8,
                                    total_timeout_seconds=9, max_output_tokens=4000)
            assert gemini is not None
            from app.llm.routing import TaskModelRouter
            gemini.interactive_quota_breaker = True
            gemini.model_router = TaskModelRouter(model, _pin_to_model(model), "gemini")
            members.append(gemini)
    return FreeInteractiveProvider(members, total_timeout_seconds=28)
