"""Opt-in independent free fallback, scoped to chat, not background LLM jobs."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace

import httpx

from app.core.config import Settings, get_settings
from app.llm.adapters import OpenAICompatibleProvider
from app.llm.base import LLMProvider
from app.llm.cascade import _FALL_THROUGH, CascadeModelRouter
from app.llm.contracts import LLMRequest, LLMResponse, Message
from app.llm.errors import ProviderRequestError, ProviderResponseError, ProviderTransportError
from app.llm.factory import create_llm_provider
from app.llm.model_aliases import VERIFIED_FREE_MODELS

GROQ_MODEL = "openai/gpt-oss-120b"
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_2 = "gemini-3.8-flash"
GEMINI_MODELS = (GEMINI_MODEL, GEMINI_MODEL_2)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

_BACKUP_PROMPT = "Puedes opinar y razonar sobre posiciones y decisiones de inversión del usuario, siempre apoyándote en los datos y fuentes del contexto. Si falta un dato, dilo en vez de inventarlo. No atribuyas opiniones a un autor si no hay fragmentos de ese autor en el contexto; en ese caso explica el concepto en general y di que no tienes una fuente concreta para atribuírselo. No añadas porcentajes, umbrales o reglas numéricas sin fuente. No deduzcas una deuda neta alta del tamaño de la deuda bruta: si falta el dato neto, indica que no está disponible. Conserva exactamente el contrato JSON y las citas del contexto cuando se exijan. Escribe en prosa plana en español, en párrafos cortos y de unas 120 palabras como máximo: sin LaTeX, sin tablas, sin listas con viñetas y sin negritas ni otro formato markdown. No escribas cifras, rangos, porcentajes ni años que no aparezcan en el contexto; explica con palabras como bajo, alto o mayor que. No uses corchetes, enlaces ni nombres de páginas web. Responde directamente, sin razonar en voz alta."


class _LanguageRejected(ProviderResponseError):
    def __init__(self, response):
        super().__init__("Candidate language rejected")
        self.response = response


class ChatFallbackProvider(LLMProvider):
    name = "chat-independent-fallback"

    def __init__(self, primary: LLMProvider, backup: LLMProvider, *, total: float = 45, delay: float = 2, validator: Callable[[LLMResponse], None] | None = None, on_response: Callable[[LLMResponse], None] | None = None, backup2: LLMProvider | None = None):
        self.backup2 = backup2
        self.validator = validator
        self.on_response = on_response
        self.primary = primary
        self.backup = backup
        self.total = total
        self.delay = min(delay, total * 2 / 3)
        self.supported_capabilities = primary.supported_capabilities & backup.supported_capabilities
        # Honest composite route, never masquerades as the primary's free model.
        super().__init__(model_router=CascadeModelRouter((primary, backup)), max_retries=0)

    def with_candidate_validator(self, validator, on_response=None):
        # Per-call clone: concurrent requests never share validation context.
        return ChatFallbackProvider(self.primary, self.backup, total=self.total,
                                    delay=self.delay, validator=validator, on_response=on_response, backup2=self.backup2)

    async def _candidate(self, provider, request, *, backup=False):
        response = await provider.complete(request)
        if self.on_response is not None:
            self.on_response(response)
        if self.validator is not None and not backup:
            from app.services.llm_output_guard import inspect_response_text
            if inspect_response_text(response.text):
                raise _LanguageRejected(response)
        try:
            if response.degraded or response.finish_reason == "length":
                raise ValueError("truncated or degraded")
            if self.validator is not None:
                self.validator(response)
        except Exception as exc:
            raise ProviderResponseError(f"Candidate rejected: {exc}") from exc
        return response

    async def complete(self, request: LLMRequest) -> LLMResponse:
        # Chat synthesis only. Other uses retain their own provider/cost gates.
        if request.task not in {"chat", "main_financial_analysis"} or request.tools:
            return await self.primary.complete(request)
        if self.primary.name == "opencode-go" and self.primary.model_router.resolve(request) not in VERIFIED_FREE_MODELS:
            raise ProviderRequestError("Chat fallback refuses a primary not verified free")
        try:
            return await asyncio.wait_for(self._race(request), timeout=self.total)
        except TimeoutError:
            raise ProviderTransportError(self.name, "timeout", 1) from None

    async def complete_cjk_retry(self, request: LLMRequest) -> LLMResponse:
        """Reintento del llm_output_guard tras rechazo CJK del primario.

        Salta directo a la cadena de respaldo verificada (Groq, luego
        Gemini) con la peticion ya anotada con el RETRY_HINT, en vez de
        repetir la carrera lenta con el modelo gratuito que acaba de fallar
        (chat real medido: 94,6 s).
        """
        try:
            return await asyncio.wait_for(self._backup_chain(request), timeout=self.total)
        except TimeoutError:
            raise ProviderTransportError(self.name, "timeout", 1) from None

    async def _backup_chain(self, request: LLMRequest) -> LLMResponse:
        """Groq gpt-oss-120b, then Gemini 3.5 Flash-Lite and Gemini 3.8 Flash (when configured); sequential, never in parallel."""
        members = [(self.backup, GROQ_MODEL)] + ([(self.backup2, model) for model in GEMINI_MODELS] if self.backup2 is not None else [])
        last: Exception | None = None
        for provider, model in members:
            try:
                return await self._candidate(provider, replace(
                    request, model=model,
                    messages=(*request.messages, Message("system", _BACKUP_PROMPT)),
                ), backup=True)
            except _FALL_THROUGH as exc:
                last = exc
        assert last is not None
        raise last

    async def _race(self, request: LLMRequest) -> LLMResponse:
        primary = asyncio.create_task(self._candidate(self.primary, request))
        tasks = [primary]
        rejected_primary = None
        try:
            done, _ = await asyncio.wait({primary}, timeout=self.delay)
            if done:
                try:
                    response = primary.result()
                    if response.degraded or response.finish_reason == "length":
                        raise ProviderResponseError("chat response was degraded")
                    return response
                except _FALL_THROUGH as exc:
                    if isinstance(exc, _LanguageRejected):
                        rejected_primary = exc.response
            # Pin backup explicitly. Never send DeepSeek aliases or effort=max.
            backup = asyncio.create_task(self._backup_chain(request))
            tasks.append(backup)
            pending = {backup} | ({primary} if not done else set())
            last = None
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:  # prefer a valid primary if both finish together
                    if task not in done:
                        continue
                    try:
                        response = task.result()
                        if response.degraded or response.finish_reason == "length":
                            raise ProviderResponseError("chat response was truncated")
                        return response
                    except _FALL_THROUGH as exc:
                        last = exc
                        if task is primary and isinstance(exc, _LanguageRejected):
                            rejected_primary = exc.response
            # Only after all candidates fail, hand the primary's language
            # rejection to complete_guarded so its RETRY_HINT can recover.
            # It never wins a race or cancels an eligible valid candidate.
            if rejected_primary is not None:
                return rejected_primary
            if last is not None:
                raise last
            raise ProviderResponseError("chat providers returned no usable response")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def create_chat_llm_provider(settings: Settings | None = None, *, client: httpx.AsyncClient | None = None) -> LLMProvider:
    settings = settings or get_settings()
    primary = create_llm_provider(settings, client=client)
    if not settings.groq_chat_fallback_enabled or primary.name == "disabled":
        return primary
    if primary.name != "opencode-go":
        raise ValueError("Groq chat fallback requires the verified OpenCode primary")
    if not (settings.groq_api_key and settings.groq_free_plan_confirmed and settings.groq_zdr_confirmed):
        raise ValueError("Groq chat requires a verified free plan, ZDR and API key")
    backup = OpenAICompatibleProvider(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        default_model=GROQ_MODEL,
        provider_name="groq",
        extra_headers={"User-Agent": "cavaai/1.0"},
        reasoning_effort="low",
        timeout_seconds=12,
        total_timeout_seconds=15,
        max_retries=0,
        max_output_tokens=2400,
        client=client,
    )
    backup2 = None
    if settings.gemini_chat_fallback_enabled:
        if not (settings.gemini_api_key and settings.gemini_free_plan_confirmed):
            raise ValueError("Gemini chat requires a verified free plan (no billing) and API key")
        backup2 = OpenAICompatibleProvider(
            api_key=settings.gemini_api_key,
            base_url=GEMINI_BASE_URL,
            default_model=GEMINI_MODEL,
            provider_name="gemini",
            reasoning_effort="low",
            timeout_seconds=15,
            total_timeout_seconds=18,
            max_retries=0,
            max_output_tokens=8000,
            client=client,
        )
    return ChatFallbackProvider(primary, backup, total=settings.llm_total_timeout_seconds, backup2=backup2)
