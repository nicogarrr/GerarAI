"""Cadena gratuita de respaldo verificada (OpenCode -> Groq -> Gemini).

Chat: carrera acotada (ChatFallbackProvider). Trabajos en segundo plano
(extracción de principios): secuencial con UN reintento transitorio
(SequentialFallbackProvider), sin carreras que dupliquen llamadas.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import replace

import httpx

from app.core.config import Settings, get_settings
from app.llm.adapters import OpenAICompatibleProvider
from app.llm.base import LLMProvider
from app.llm.cascade import _FALL_THROUGH, CascadeModelRouter
from app.llm.contracts import LLMRequest, LLMResponse, Message
from app.llm.errors import (
    ProviderHTTPError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTransportError,
)
from app.llm.factory import create_llm_provider
from app.llm.model_aliases import VERIFIED_FREE_MODELS

logger = logging.getLogger(__name__)

GROQ_MODEL = "openai/gpt-oss-120b"
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_2 = "gemini-3.8-flash"
GEMINI_MODELS = (GEMINI_MODEL, GEMINI_MODEL_2)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

_BACKUP_PROMPT = "Puedes opinar y razonar sobre posiciones y decisiones de inversión del usuario, siempre apoyándote en los datos y fuentes del contexto. Si falta un dato, dilo en vez de inventarlo. No atribuyas opiniones a un autor si no hay fragmentos de ese autor en el contexto; en ese caso explica el concepto en general y di que no tienes una fuente concreta para atribuírselo. No añadas porcentajes, umbrales o reglas numéricas sin fuente. No deduzcas una deuda neta alta del tamaño de la deuda bruta: si falta el dato neto, indica que no está disponible. Conserva exactamente el contrato JSON y las citas del contexto cuando se exijan. Escribe en prosa plana en español, en párrafos cortos y de unas 120 palabras como máximo: sin LaTeX, sin tablas, sin listas con viñetas y sin negritas ni otro formato markdown. No escribas cifras, rangos, porcentajes ni años que no aparezcan en el contexto; explica con palabras como bajo, alto o mayor que. No uses corchetes, enlaces ni nombres de páginas web. Responde directamente, sin razonar en voz alta."


#: Enfriamiento por (proveedor, modelo) tras un 429: el siguiente chat no
#: pierde segundos en un miembro cuya cuota gratuita acaba de agotarse.
QUOTA_COOLDOWN_SECONDS = 90.0
_cooldowns: dict[tuple[str, str], float] = {}


def _member_key(provider, model: str | None) -> tuple[str, str]:
    return (str(getattr(provider, "name", "?")), str(model or ""))


def _is_cooling(provider, model: str | None) -> bool:
    return _cooldowns.get(_member_key(provider, model), 0.0) > time.monotonic()


def _note_failure(provider, model: str | None, exc: Exception) -> None:
    if isinstance(exc, ProviderHTTPError) and exc.status_code == 429:
        _cooldowns[_member_key(provider, model)] = time.monotonic() + QUOTA_COOLDOWN_SECONDS


def reset_quota_cooldowns() -> None:
    _cooldowns.clear()


def is_quota_exhausted(exc: BaseException) -> bool:
    """True si el fallo es cuota gratuita agotada (429) y no una caída."""
    return isinstance(exc, ProviderHTTPError) and exc.status_code == 429


class _LanguageRejected(ProviderResponseError):
    def __init__(self, response):
        super().__init__("Candidate language rejected")
        self.response = response


class ChatFallbackProvider(LLMProvider):
    name = "chat-independent-fallback"

    def __init__(self, primary: LLMProvider, backup: LLMProvider, *, total: float = 45, delay: float = 2, validator: Callable[[LLMResponse], None] | None = None, on_response: Callable[[LLMResponse], None] | None = None, backup2: LLMProvider | None = None, extra_backups: tuple[tuple[LLMProvider, str], ...] = ()):
        self.backup2 = backup2
        self.extra_backups = extra_backups
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
                                    delay=self.delay, validator=validator, on_response=on_response, backup2=self.backup2, extra_backups=self.extra_backups)

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
        members = [(self.backup, GROQ_MODEL)] + ([(self.backup2, model) for model in GEMINI_MODELS] if self.backup2 is not None else []) + list(self.extra_backups)
        # Miembros con la cuota recién agotada se saltan; si TODOS están
        # enfriándose se prueban igualmente (mejor intentar que callar).
        ready = [m for m in members if not _is_cooling(*m)]
        last: Exception | None = None
        for provider, model in ready or members:
            try:
                return await self._candidate(provider, replace(
                    request, model=model,
                    messages=(*request.messages, Message("system", _BACKUP_PROMPT)),
                ), backup=True)
            except _FALL_THROUGH as exc:
                _note_failure(provider, model, exc)
                last = exc
        assert last is not None
        raise last

    async def _race(self, request: LLMRequest) -> LLMResponse:
        primary_model = self.primary.model_router.resolve(request) if getattr(self.primary, "model_router", None) else None
        if _is_cooling(self.primary, primary_model):
            # Cuota del primario agotada hace segundos: directo a la cadena.
            return await self._backup_chain(request)
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
                    _note_failure(self.primary, primary_model, exc)
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
                        if task is primary:
                            _note_failure(self.primary, primary_model, exc)
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


_TRANSIENT_TRANSPORT_REASONS = frozenset({"read_timeout", "connect_timeout", "write_timeout", "pool_timeout", "timeout"})
_EMPTY_REPLY_MARKERS = ("returned no assistant message", "returned an empty assistant message")


def _is_transient(exc: Exception) -> bool:
    """Timeout del transporte o respuesta vacía: reintentable una vez. Nada de salidas inválidas."""
    if isinstance(exc, ProviderTransportError):
        return exc.reason in _TRANSIENT_TRANSPORT_REASONS
    if isinstance(exc, ProviderResponseError):
        return any(marker in str(exc) for marker in _EMPTY_REPLY_MARKERS)
    return False


class SequentialFallbackProvider(LLMProvider):
    """Respaldo para trabajos en segundo plano (extracción de principios).

    Secuencial, nunca en carrera: un documento son hasta ~40 lotes y una
    carrera como la del chat duplicaría las llamadas. El primario tiene UN
    reintento solo ante error transitorio (timeout o respuesta vacía); si
    vuelve a fallar, o ante cualquier otro error de proveedor (caída, cuota,
    respuesta ilegible), se prueba la cadena gratuita verificada Groq ->
    Gemini con el modelo pineado. `ProviderRequestError` (fallo nuestro, una
    petición mal construida) se propaga sin probar más miembros.
    """

    name = "background-sequential-fallback"

    def __init__(self, primary: LLMProvider, backup: LLMProvider | None = None, backup2: LLMProvider | None = None, *, retry_pause: float = 2.0) -> None:
        self.primary, self.backup, self.backup2 = primary, backup, backup2
        self.retry_pause = retry_pause
        members = tuple(p for p in (primary, backup, backup2) if p is not None)
        self.supported_capabilities = frozenset.intersection(*(m.supported_capabilities for m in members))
        # Ruta compuesta honesta: nunca se anuncia como el modelo gratuito del primario.
        super().__init__(model_router=CascadeModelRouter(members), max_retries=0)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            return await self.primary.complete(request)
        except _FALL_THROUGH as exc:
            last: Exception = exc
        if _is_transient(last):
            logger.warning("background LLM: %s transitorio (%s); un reintento", self.primary.name, type(last).__name__)
            await asyncio.sleep(self.retry_pause)
            try:
                return await self.primary.complete(request)
            except _FALL_THROUGH as exc:
                last = exc
        for provider, models in ((self.backup, (GROQ_MODEL,)), (self.backup2, GEMINI_MODELS)):
            if provider is None:
                continue
            for model in models:
                try:
                    return await provider.complete(replace(request, model=model))
                except _FALL_THROUGH as exc:
                    last = exc
                    logger.warning("background LLM: %s falló (%s); siguiente proveedor", provider.name, type(exc).__name__)
        raise last


def _groq_backup(
    settings: Settings,
    client: httpx.AsyncClient | None,
    *,
    timeout_seconds: float = 12,
    total_timeout_seconds: float = 15,
    max_output_tokens: int = 2400,
) -> OpenAICompatibleProvider | None:
    if not settings.groq_chat_fallback_enabled:
        return None
    if not (settings.groq_api_key and settings.groq_free_plan_confirmed and settings.groq_zdr_confirmed):
        raise ValueError("Groq chat requires a verified free plan, ZDR and API key")
    return OpenAICompatibleProvider(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        default_model=GROQ_MODEL,
        provider_name="groq",
        extra_headers={"User-Agent": "cavaai/1.0"},
        reasoning_effort="low",
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        max_retries=0,
        max_output_tokens=max_output_tokens,
        client=client,
    )


def _gemini_backup(
    settings: Settings,
    client: httpx.AsyncClient | None,
    *,
    timeout_seconds: float = 15,
    total_timeout_seconds: float = 18,
    max_output_tokens: int = 8000,
) -> OpenAICompatibleProvider | None:
    if not settings.gemini_chat_fallback_enabled:
        return None
    if not (settings.gemini_api_key and settings.gemini_free_plan_confirmed):
        raise ValueError("Gemini chat requires a verified free plan (no billing) and API key")
    return OpenAICompatibleProvider(
        api_key=settings.gemini_api_key,
        base_url=GEMINI_BASE_URL,
        default_model=GEMINI_MODEL,
        provider_name="gemini",
        reasoning_effort="low",
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        max_retries=0,
        max_output_tokens=max_output_tokens,
        client=client,
    )


def _openrouter_backup(settings: Settings, client: httpx.AsyncClient | None) -> tuple[tuple[OpenAICompatibleProvider, str], ...]:
    """OpenRouter solo si ya hay clave y el modelo es :free; nunca crea cuentas."""
    key = settings.openrouter_api_key
    model = settings.openrouter_model
    if not (key and str(key).strip()) or not model.endswith(":free"):
        return ()
    return ((OpenAICompatibleProvider(
        api_key=str(key), base_url=settings.openrouter_base_url, default_model=model,
        provider_name="openrouter", timeout_seconds=15, total_timeout_seconds=18,
        max_retries=0, max_output_tokens=2400, client=client,
    ), model),)


def create_chat_llm_provider(settings: Settings | None = None, *, client: httpx.AsyncClient | None = None) -> LLMProvider:
    settings = settings or get_settings()
    # Chat interactivo: presupuesto corto propio (chat_total_timeout_seconds,
    # no el tope de llamadas largas) y primario con reasoning reducido para
    # que compita en la carrera en vez de perderla siempre y quedar cancelado
    # a medias en el bridge (BrokenPipe).
    primary = create_llm_provider(
        settings,
        client=client,
        reasoning_effort=settings.opencode_go_chat_reasoning_effort,
        # Un intento por modelo: un 429 del free tier no se repite (el
        # reintento duplicaba la espera); la carrera ya tiene respaldo Groq.
        max_retries=0,
    )
    if not settings.groq_chat_fallback_enabled or primary.name == "disabled":
        return primary
    if primary.name != "opencode-go":
        raise ValueError("Groq chat fallback requires the verified OpenCode primary")
    backup = _groq_backup(settings, client)
    assert backup is not None  # el flag de arriba lo garantiza
    backup2 = _gemini_backup(settings, client)
    return ChatFallbackProvider(primary, backup, total=settings.chat_total_timeout_seconds, backup2=backup2,
                                extra_backups=_openrouter_backup(settings, client))


def create_background_llm_provider(settings: Settings | None = None, *, client: httpx.AsyncClient | None = None) -> LLMProvider:
    """Proveedor para trabajos en segundo plano: primario con reintento
    transitorio y la cadena gratuita Groq/Gemini en secuencia.

    Reutiliza las mismas claves y flags verificados del chat. Un respaldo mal
    configurado se salta con un aviso en el log en vez de romper el trabajo:
    el primario solo ya es el comportamiento anterior.
    """
    settings = settings or get_settings()
    # max_retries=0 en el primario: el reintento UNICO de la llamada larga lo
    # hace SequentialFallbackProvider ante error transitorio. Con reintentos
    # internos ademas, un bridge caido costaria 2x(120+120) s por lote antes
    # de llegar a Groq/Gemini.
    primary = create_llm_provider(settings, client=client, max_retries=0)
    if primary.name == "disabled":
        return primary
    # Presupuestos de trabajo largo, no de chat: un lote de extraccion son
    # ~6k tokens de entrada y hasta 3.000 de salida; con los 12-18 s del chat
    # los respaldos gratuitos caian en read timeout y el job de principios
    # moria como «La extracción tardó demasiado» (prod, 18 oct 2026).
    try:
        backup = _groq_backup(
            settings, client, timeout_seconds=60, total_timeout_seconds=75,
        )
    except ValueError:
        logger.warning("background LLM fallback: Groq mal configurado; se omite el respaldo")
        backup = None
    try:
        backup2 = _gemini_backup(
            settings, client, timeout_seconds=90, total_timeout_seconds=110,
        )
    except ValueError:
        logger.warning("background LLM fallback: Gemini mal configurado; se omite el respaldo")
        backup2 = None
    if backup is None and backup2 is None:
        return primary
    return SequentialFallbackProvider(primary, backup, backup2)
