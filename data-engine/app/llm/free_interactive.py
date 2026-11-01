"""Bounded owner-approved debate chain.

Orden: modelo Go aprobado (si la suscripcion esta confirmada) y su fallback
explicito -> OpenCode free (deepseek, /zen/v1) -> AI Studio solo con
GEMINI_CHAT_FALLBACK_ENABLED=true. Los free reales solo entran cuando el
modelo configurado es free (bridge legacy).
Con clave propia del tenant se usa su proveedor, sin respaldos.
Nunca usa la cascada generica Gemini/OpenRouter ni overrides de pago.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import Settings, get_settings
from app.llm.cascade import _FALL_THROUGH, CascadeProvider
from app.llm.chat_provider import GEMINI_MODELS, _gemini_backup, _opencode_free_backup
from app.llm.contracts import LLMRequest
from app.llm.errors import LLMError, ProviderHTTPError, ProviderResponseError, ProviderTransportError
from app.llm.factory import _opencode_go, _pin_to_model, create_llm_provider
from app.llm.model_aliases import (
    GO_SUBSCRIPTION_MODELS,
    VERIFIED_FREE_MODELS,
    is_owner_approved_model,
)
from app.llm.tenant_config import current_tenant_llm_config

logger = logging.getLogger(__name__)


class FreeLLMUnavailable(LLMError):
    def __init__(self, *, quota: bool = False):
        self.quota = quota
        super().__init__("El modelo configurado ha agotado su cuota, vuelve más tarde" if quota else
                         "El modelo configurado no está disponible, vuelve más tarde")


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
    if current_tenant_llm_config() is not None:
        # Clave propia del usuario (Ajustes): el debate usa SU proveedor y
        # modelo, nunca la clave de la plataforma ni modelos free de respaldo.
        return create_llm_provider(settings, client=client, max_retries=0,
                                   timeout_seconds=12, total_timeout_seconds=28)
    if not settings.llm_enabled or settings.llm_provider == "disabled" or not settings.opencode_go_api_key:
        raise FreeLLMUnavailable()
    # Never use the generic Gemini/OpenRouter cascade: keys may carry billing.
    # Solo el modelo configurado (y su fallback explicito). Antes se anadian
    # SIEMPRE los free reales (deepseek-v4.1-flash-free, space-bunny-free...)
    # con effort low como respaldo silencioso del modelo Go del dueno; ahora
    # solo entran si el propio modelo configurado es free (bridge legacy).
    configured = [
        m for m in (settings.opencode_go_model, settings.opencode_go_fallback_model)
        if m and is_owner_approved_model(m, settings)
    ]
    legacy_free = settings.opencode_go_model in VERIFIED_FREE_MODELS
    models = list(dict.fromkeys(configured + (sorted(VERIFIED_FREE_MODELS) if legacy_free else [])))
    if not models:
        raise FreeLLMUnavailable()
    members = []
    for model in models:
        pinned = settings.model_copy(update={
            "opencode_go_model": model, "opencode_go_fallback_model": "",
            "llm_model_overrides": _pin_to_model(model),
        })
        members.append(_opencode_go(pinned, client=client, max_retries=0,
                                    timeout_seconds=12, total_timeout_seconds=14,
                                    reasoning_effort=(
                                        "high" if model in GO_SUBSCRIPTION_MODELS else "low"
                                    )))
    for member in members:
        member.interactive_quota_breaker = True
    # OpenCode free (deepseek, /zen/v1): respaldo de plataforma entre Go y
    # Gemini, gasto 0. No en el bridge legacy (el modelo configurado YA es
    # free) ni si duplica un miembro ya presente.
    if not legacy_free and settings.opencode_free_chat_fallback_active:
        free_model = (settings.opencode_free_model or "").strip()
        if free_model and free_model not in models:
            free_member = _opencode_free_backup(
                settings, client, timeout_seconds=8,
                total_timeout_seconds=9, max_output_tokens=4000,
            )
            if free_member is not None:
                free_member.interactive_quota_breaker = True
                members.append(free_member)
    # AI Studio is free only with confirmed no billing, not merely by model ID.
    # Reuse the existing guard; never add Gemini to the OpenCode free registry.
    if settings.gemini_chat_fallback_active:
        for model in GEMINI_MODELS:
            gemini = _gemini_backup(settings, client, timeout_seconds=8,
                                    total_timeout_seconds=9, max_output_tokens=4000)
            assert gemini is not None
            from app.llm.routing import TaskModelRouter
            gemini.interactive_quota_breaker = True
            gemini.model_router = TaskModelRouter(model, _pin_to_model(model), "gemini")
            members.append(gemini)
    return FreeInteractiveProvider(members, total_timeout_seconds=28)
