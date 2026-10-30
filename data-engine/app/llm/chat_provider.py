"""Cadena de chat y respaldo (OpenCode Go -> Groq -> Gemini).

Chat: carrera acotada (ChatFallbackProvider). Trabajos en segundo plano
(extracción de principios): secuencial con UN reintento transitorio
(SequentialFallbackProvider), sin carreras que dupliquen llamadas.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import replace

import httpx

from app.core.config import Settings, get_settings
from app.llm.adapters import DisabledProvider, OpenAICompatibleProvider
from app.llm.base import LLMProvider
from app.llm.cascade import _FALL_THROUGH, CascadeModelRouter
from app.llm.contracts import LLMRequest, LLMResponse, Message
from app.llm.errors import (
    ProviderHTTPError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTransportError,
)
from app.llm.factory import _pin_to_model, create_llm_provider
from app.llm.interactive_deadline import remaining_seconds
from app.llm.model_aliases import is_owner_approved_model
from app.llm.response_cache import build_response_cache
from app.llm.tenant_config import current_tenant_llm_config

logger = logging.getLogger(__name__)

GROQ_MODEL = "openai/gpt-oss-120b"
#: Modelo de la suscripcion OpenCode Go (no es gratuito; solo con el interruptor
#: CHAT_GO_SUBSCRIPTION_ENABLED). Id verificado en /zen/go/v1/models.
GO_SUBSCRIPTION_MODEL = "deepseek-v4.1-flash"
GO_SUBSCRIPTION_PROVIDER = "opencode-go-subscription"
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_2 = "gemini-3.8-flash"
GEMINI_MODELS = (GEMINI_MODEL, GEMINI_MODEL_2)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

_BACKUP_PROMPT = "Puedes opinar y razonar sobre posiciones y decisiones de inversión del usuario, siempre apoyándote en los datos y fuentes del contexto. Si falta un dato, dilo en vez de inventarlo. No atribuyas opiniones a un autor si no hay fragmentos de ese autor en el contexto; en ese caso explica el concepto en general y di que no tienes una fuente concreta para atribuírselo. No añadas porcentajes, umbrales o reglas numéricas sin fuente. No deduzcas una deuda neta alta del tamaño de la deuda bruta: si falta el dato neto, indica que no está disponible. Conserva exactamente el contrato JSON y las citas del contexto cuando se exijan. Escribe en prosa plana en español, en párrafos cortos y de unas 120 palabras como máximo: sin LaTeX, sin tablas, sin listas con viñetas y sin negritas ni otro formato markdown. No escribas cifras, rangos, porcentajes ni años que no aparezcan en el contexto; explica con palabras como bajo, alto o mayor que. No uses corchetes, enlaces ni nombres de páginas web. Responde directamente, sin razonar en voz alta."

_BACKUP_PROMPT_EN = "You may give opinions and reason about the user's positions and investment decisions, always grounded in the data and sources in the context. If a data point is missing, say so instead of inventing it. Do not attribute opinions to an author unless there are fragments by that author in the context; otherwise explain the concept in general and say you have no specific source to attribute it to. Do not add percentages, thresholds or numeric rules without a source. Do not infer high net debt from the size of gross debt: if the net figure is missing, say it is not available. Keep the JSON contract and the context citations exactly when they are required. Write in plain English prose, in short paragraphs of about 120 words at most: no LaTeX, no tables, no bullet lists and no bold or other markdown formatting. Do not write figures, ranges, percentages or years that do not appear in the context; explain with words like low, high or higher than. Do not use brackets, links or website names. Answer directly, without thinking out loud."


def _backup_prompt() -> str:
    """Refuerzo de sistema del respaldo, en el idioma de la generacion (i18n B)."""
    from app.core.i18n import current_language

    return _BACKUP_PROMPT_EN if current_language() == "en" else _BACKUP_PROMPT


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


def _failure_label(provider, model: str | None, exc: BaseException) -> str:
    """"proveedor:modelo:Clase[status]" sin mensaje, URL ni cabeceras."""
    status = getattr(exc, "status_code", None) if isinstance(exc, ProviderHTTPError) else None
    return f"{getattr(provider, 'name', '?')}:{model or '?'}:{type(exc).__name__}{status or ''}"


def _with_trail(response: LLMResponse, trail: list[str]) -> LLMResponse:
    return replace(response, fallback_trail=(*trail, *response.fallback_trail)) if trail else response


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

    def __init__(self, primary: LLMProvider, backup: LLMProvider, *, total: float = 45, delay: float | None = None, validator: Callable[[LLMResponse], None] | None = None, on_response: Callable[[LLMResponse], None] | None = None, backup2: LLMProvider | None = None, extra_backups: tuple[tuple[LLMProvider, str], ...] = (), backup_model: str = GROQ_MODEL, settings: Settings | None = None):
        self.backup_model = backup_model
        self.backup2 = backup2
        self.extra_backups = extra_backups
        self.validator = validator
        self.on_response = on_response
        self.settings = settings
        self.primary = primary
        self.backup = backup
        self.total = total
        # Plazo de OpenCode Go antes de pasar al respaldo (no es una ventaja
        # de salida: el respaldo NUNCA corre a la vez que Go). Por defecto 2/3
        # del presupuesto total, y el tercio restante queda para el respaldo.
        self.delay = min(delay, total * 2 / 3) if delay is not None else total * 2 / 3
        self.supported_capabilities = primary.supported_capabilities & backup.supported_capabilities
        # Honest composite route, never masquerades as the primary's free model.
        super().__init__(model_router=CascadeModelRouter((primary, backup)), max_retries=0)

    def with_candidate_validator(self, validator, on_response=None):
        # Per-call clone: concurrent requests never share validation context.
        return ChatFallbackProvider(self.primary, self.backup, total=self.total,
                                    delay=self.delay, validator=validator, on_response=on_response, backup2=self.backup2, extra_backups=self.extra_backups, backup_model=self.backup_model, settings=self.settings)

    async def _candidate(self, provider, request, *, backup=False):
        response = await provider.complete(request)
        if self.on_response is not None:
            self.on_response(response)
        if self.validator is not None and not backup:
            from app.core.i18n import current_language
            from app.services.llm_output_guard import inspect_response_text
            if inspect_response_text(response.text, expected_language=current_language()):
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
        if self.primary.name == "opencode-go":
            settings = self.settings or get_settings()
            if not is_owner_approved_model(
                self.primary.model_router.resolve(request), settings
            ):
                raise ProviderRequestError(
                    "Chat fallback refuses a primary not owner-approved"
                )
        try:
            return await asyncio.wait_for(self._race(request), timeout=remaining_seconds(self.total))
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
            return await asyncio.wait_for(self._backup_chain(request), timeout=remaining_seconds(self.total))
        except TimeoutError:
            raise ProviderTransportError(self.name, "timeout", 1) from None

    async def _backup_chain(self, request: LLMRequest) -> LLMResponse:
        """Groq gpt-oss-120b, then Gemini 3.5 Flash-Lite and Gemini 3.8 Flash (when configured); sequential, never in parallel."""
        members = [(self.backup, self.backup_model)] + ([(self.backup2, model) for model in GEMINI_MODELS] if self.backup2 is not None else []) + list(self.extra_backups)
        # Do not re-probe exhausted members until their cooldown expires.
        ready = [m for m in members if not _is_cooling(*m)]
        last: Exception | None = None
        trail = [f"{getattr(p, 'name', '?')}:{m or '?'}:cooling" for p, m in members if _is_cooling(p, m)]
        if not ready:
            raise ProviderHTTPError(self.name, 429)
        for provider, model in ready:
            member_request = replace(
                request, model=model,
                messages=(*request.messages, Message("system", _backup_prompt())),
            )
            logger.info("chat backup attempt provider=%s model=%s", provider.name, model)
            try:
                return _with_trail(await self._candidate(provider, member_request, backup=True), trail)
            except _FALL_THROUGH as exc:
                trail.append(_failure_label(provider, model, exc))
                logger.warning("chat backup failed provider=%s model=%s error=%s detail=%.200s",
                               provider.name, model, type(exc).__name__, exc)
                # 503 de capacidad (Gemini "high demand"): un reintento corto
                # dentro del plazo restante antes de pasar al siguiente miembro.
                if isinstance(exc, ProviderHTTPError) and exc.status_code == 503:
                    try:
                        await asyncio.sleep(min(0.5, remaining_seconds(self.total)))
                        logger.info("chat backup retry provider=%s model=%s", provider.name, model)
                        return _with_trail(await self._candidate(provider, member_request, backup=True), trail)
                    except _FALL_THROUGH as retry_exc:
                        logger.warning("chat backup retry failed provider=%s model=%s error=%s detail=%.200s",
                                       provider.name, model, type(retry_exc).__name__, retry_exc)
                        exc = retry_exc
                _note_failure(provider, model, exc)
                last = exc
        assert last is not None
        raise last

    async def _race(self, request: LLMRequest) -> LLMResponse:
        """Go primero y SOLO despues el respaldo (nombre historico: ya no hay carrera).

        Decision del dueno (2026-10-27): el respaldo arranca unicamente cuando
        OpenCode Go devuelve un error, una respuesta inutilizable o agota su
        plazo (``self.delay``). La respuesta del respaldo lleva en
        ``fallback_trail`` el motivo del fallo de Go como primer elemento, para
        que el chat lo muestre («Respondido por respaldo ...»).
        """
        primary_model = self.primary.model_router.resolve(request) if getattr(self.primary, "model_router", None) else None
        primary_name = getattr(self.primary, "name", "?")
        rejected_primary = None
        if _is_cooling(self.primary, primary_model):
            # Cuota del primario agotada hace segundos: directo a la cadena.
            primary_label = f"{primary_name}:{primary_model or '?'}:cooling"
        else:
            primary = asyncio.create_task(self._candidate(self.primary, request))
            try:
                done, _ = await asyncio.wait({primary}, timeout=self.delay)
            finally:
                if not primary.done():
                    primary.cancel()
                await asyncio.gather(primary, return_exceptions=True)
            if done:
                try:
                    response = primary.result()
                    if response.degraded or response.finish_reason == "length":
                        raise ProviderResponseError("chat response was degraded")
                    return response
                except _FALL_THROUGH as exc:
                    _note_failure(self.primary, primary_model, exc)
                    primary_label = _failure_label(self.primary, primary_model, exc)
                    if isinstance(exc, _LanguageRejected):
                        rejected_primary = exc.response
            else:
                primary_label = f"{primary_name}:{primary_model or '?'}:timeout"
        try:
            response = await self._backup_chain(request)
        except _FALL_THROUGH:
            # Todos fallan: el rechazo de idioma del primario vuelve a
            # complete_guarded para que su RETRY_HINT lo intente recuperar.
            if rejected_primary is not None:
                return rejected_primary
            raise
        logger.warning(
            "llm.fallback provider=%s model=%s because=%s",
            response.provider, response.model, primary_label,
        )
        return _with_trail(response, [primary_label])


_GO_PROVIDER_NAMES = frozenset({"opencode-go", GO_SUBSCRIPTION_PROVIDER})
_PROVIDER_LABELS = {"groq": "Groq", "gemini": "Gemini", "openrouter": "OpenRouter"}


def _reason_es(reason: str) -> str:
    """Motivo del fallo de Go en espanol llano (sin URLs ni detalles internos)."""
    if reason == "timeout":
        return "no respondió a tiempo"
    if reason == "cooling":
        return "alcanzó su límite de uso hace un momento"
    if reason.startswith("ProviderHTTPError"):
        code = reason.removeprefix("ProviderHTTPError")
        if code == "429":
            return "límite de uso alcanzado (HTTP 429)"
        if code.startswith("5"):
            return f"error del servidor (HTTP {code})"
        return f"error HTTP {code}" if code else "error HTTP"
    if reason.startswith("ProviderTransportError"):
        return "error de conexión"
    if reason == "_LanguageRejected":
        return "su respuesta no estaba en español"
    if reason.startswith("ProviderResponseError"):
        return "respuesta vacía o incompleta"
    return f"error ({reason})"


def _reason_en(reason: str) -> str:
    """Plain-English version of the Go failure reason (i18n B)."""
    if reason == "timeout":
        return "it did not respond in time"
    if reason == "cooling":
        return "it hit its usage limit a moment ago"
    if reason.startswith("ProviderHTTPError"):
        code = reason.removeprefix("ProviderHTTPError")
        if code == "429":
            return "usage limit reached (HTTP 429)"
        if code.startswith("5"):
            return f"server error (HTTP {code})"
        return f"HTTP error {code}" if code else "HTTP error"
    if reason.startswith("ProviderTransportError"):
        return "connection error"
    if reason == "_LanguageRejected":
        return "its response was not in English"
    if reason.startswith("ProviderResponseError"):
        return "empty or incomplete response"
    return f"error ({reason})"


def fallback_notice(response: LLMResponse, *, lang: str = "es") -> str | None:
    """Aviso visible cuando respondio un respaldo porque OpenCode Go fallo.

    None si respondio Go (o una respuesta sin rastro de fallo de Go).
    ``lang`` (i18n B) redacta el aviso en el idioma de la conversacion.
    """
    trail = getattr(response, "fallback_trail", ()) or ()
    if not trail or response.provider in _GO_PROVIDER_NAMES:
        return None
    first = str(trail[0])
    if first.split(":", 1)[0] not in _GO_PROVIDER_NAMES:
        return None
    name = _PROVIDER_LABELS.get(response.provider, response.provider)
    reason = first.rsplit(":", 1)[-1]
    if lang == "en":
        return f"Answered by backup ({name}) because OpenCode Go failed: {_reason_en(reason)}."
    return f"Respondido por respaldo ({name}) porque OpenCode Go falló: {_reason_es(reason)}."


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


GO_COMPACT_SECTIONS_HINT = (
    " Salida compacta: cada `body` de seccion maximo 220 caracteres (una o dos frases con los"
    " datos y su periodo; sin repetir el contexto); `answer` maximo 700 caracteres; mantén"
    " todas las citas exactas que sostienen cada afirmacion y los 8 apartados."
)


class GoSubscriptionChatProvider(OpenAICompatibleProvider):
    """Adaptador del endpoint OpenCode Go (/zen/go/v1).

    Go responde HTTP 400 a `response_format`: el contrato JSON se pide en el
    prompt y se retira del sobre. Si el modelo envuelve el JSON en un bloque
    ``` se desenvuelve para que los validadores de citas vean el JSON puro.
    Cabeceras: User-Agent propio y `x-opencode-session` (documentado por Go).
    """

    def _build_payload(self, request: LLMRequest, model: str) -> dict:
        payload = super()._build_payload(request, model)
        response_format = payload.pop("response_format", None)
        if response_format:
            instruction = "Responde SOLO con un objeto JSON valido, sin texto fuera del JSON ni bloque de codigo."
            schema = (response_format.get("json_schema") or {}).get("schema")
            if schema:
                instruction += " Debe cumplir este esquema JSON: " + json.dumps(schema, ensure_ascii=False, sort_keys=True)
                sections = (schema.get("properties") or {}).get("sections")
                if isinstance(sections, dict) and sections.get("minItems") == sections.get("maxItems") == 8:
                    # Medido 25-oct: con la peticion real Go agoto los 2600 tokens de salida
                    # (finish=length, JSON cortado). Salida corta = menos tokens y menos riesgo
                    # de truncado; las citas y los hechos se conservan.
                    instruction += GO_COMPACT_SECTIONS_HINT
            messages = payload["messages"]
            last = messages[-1] if messages else None
            if last and last.get("role") == "user" and isinstance(last.get("content"), str):
                last["content"] = f"{last['content']}\n\n{instruction}"
            else:
                messages.append({"role": "user", "content": instruction})
        return payload

    async def _complete(self, request: LLMRequest, model: str) -> LLMResponse:
        response = await super()._complete(request, model)
        if request.response_format is not None:
            text = response.message.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else ""
                text = text.rsplit("```", 1)[0].strip()
                response = replace(response, message=replace(response.message, content=text))
        return response


def _go_subscription_primary(settings: Settings, client: httpx.AsyncClient | None) -> OpenAICompatibleProvider | None:
    """Primario por la suscripcion Go; None si el interruptor esta apagado."""
    if not settings.llm_enabled or (settings.llm_provider or "").strip().lower() == "disabled":
        return None
    if not settings.chat_go_subscription_enabled:
        return None
    if not (settings.opencode_go_api_key and settings.opencode_go_api_key.strip()):
        return None
    fallback = (settings.opencode_go_fallback_model or "").strip()
    models = {GO_SUBSCRIPTION_MODEL}
    if fallback:
        models.add(fallback)
    overrides = _pin_to_model(GO_SUBSCRIPTION_MODEL)
    if fallback:
        overrides.pop(fallback, None)
    return GoSubscriptionChatProvider(
        api_key=settings.opencode_go_api_key,
        base_url=settings.chat_go_subscription_base_url,
        default_model=GO_SUBSCRIPTION_MODEL,
        provider_name=GO_SUBSCRIPTION_PROVIDER,
        model_overrides=overrides,
        fallback_model=fallback or None,
        extra_headers={
            "User-Agent": "GerarAI-chat/1.0",
            "x-opencode-session": settings.opencode_go_session,
        },
        reasoning_effort=settings.opencode_go_chat_reasoning_effort,
        reasoning_effort_models=models,
        hidden_reasoning_models=models,
        hidden_reasoning_min_tokens=max(settings.llm_hidden_reasoning_min_tokens, settings.chat_go_min_output_tokens),
        max_output_tokens=settings.llm_max_output_tokens,
        max_retries=0,
        timeout_seconds=min(settings.llm_timeout_seconds, settings.chat_total_timeout_seconds),
        total_timeout_seconds=settings.chat_total_timeout_seconds,
        response_cache=build_response_cache(settings),
        client=client,
    )


def _groq_backup(
    settings: Settings,
    client: httpx.AsyncClient | None,
    *,
    timeout_seconds: float = 12,
    total_timeout_seconds: float = 15,
    max_output_tokens: int = 2400,
) -> OpenAICompatibleProvider | None:
    if not settings.groq_chat_fallback_active:
        return None
    if not (settings.groq_api_key and settings.groq_free_plan_confirmed and settings.groq_zdr_confirmed):
        raise ValueError("Groq chat requires a verified free plan, ZDR and API key")
    return OpenAICompatibleProvider(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        default_model=GROQ_MODEL,
        provider_name="groq",
        extra_headers={"User-Agent": "gerarai/1.0"},
        reasoning_effort="low",
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        max_retries=0,
        max_output_tokens=max_output_tokens,
        # gpt-oss es modelo de razonamiento: sin el bump, un max_tokens de
        # 600 (chat general) lo consumia el razonamiento y la respuesta
        # llegaba truncada (finish_reason=length) -> "Candidate rejected".
        hidden_reasoning_models=frozenset({GROQ_MODEL}),
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
    if not settings.gemini_chat_fallback_active:
        return None
    if not (settings.gemini_api_key and settings.gemini_free_plan_confirmed):
        raise ValueError("Gemini chat requires a verified free plan (no billing) and API key")
    provider = OpenAICompatibleProvider(
        api_key=settings.gemini_api_key,
        base_url=GEMINI_BASE_URL,
        default_model=GEMINI_MODEL,
        provider_name="gemini",
        reasoning_effort="low",
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        max_retries=0,
        max_output_tokens=max_output_tokens,
        # Gemini 3.x tambien razona: mismo bump de max_tokens que Groq.
        hidden_reasoning_models=frozenset(GEMINI_MODELS),
        client=client,
    )
    return provider


def _openrouter_backup(settings: Settings, client: httpx.AsyncClient | None) -> tuple[tuple[OpenAICompatibleProvider, str], ...]:
    """OpenRouter :free como ultimo respaldo (tras fallar Go): flag true/auto con clave."""
    key = settings.openrouter_api_key
    model = settings.openrouter_model
    if not settings.openrouter_chat_fallback_active:
        return ()
    if not (key and str(key).strip()) or not model.endswith(":free"):
        return ()
    return ((OpenAICompatibleProvider(
        api_key=str(key), base_url=settings.openrouter_base_url, default_model=model,
        provider_name="openrouter", timeout_seconds=15, total_timeout_seconds=18,
        max_retries=0, max_output_tokens=2400, client=client,
    ), model),)


def create_chat_llm_provider(settings: Settings | None = None, *, client: httpx.AsyncClient | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if current_tenant_llm_config() is not None:
        # El tenant paga su clave: sin respaldos de plataforma (Groq/Gemini)
        # ni modelos de OpenCode. Mismo contrato fail-closed del factory.
        return create_llm_provider(
            settings,
            client=client,
            max_retries=0,
            timeout_seconds=min(settings.llm_timeout_seconds, settings.chat_total_timeout_seconds),
            total_timeout_seconds=settings.chat_total_timeout_seconds,
        )
    if not settings.llm_enabled or (settings.llm_provider or "").strip().lower() == "disabled":
        return DisabledProvider("disabled_by_configuration")
    # Chat interactivo: presupuesto corto propio (chat_total_timeout_seconds,
    # no el tope de llamadas largas) y primario con reasoning reducido para
    # que compita en la carrera en vez de perderla siempre y quedar cancelado
    # a medias en el bridge (BrokenPipe).
    go_subscription = _go_subscription_primary(settings, client)
    if (
        go_subscription is None
        and not is_owner_approved_model(settings.opencode_go_model, settings)
    ):
        return DisabledProvider("chat_primary_not_verified_free")
    fallback = settings.opencode_go_fallback_model.strip()
    if fallback and not is_owner_approved_model(fallback, settings):
        return DisabledProvider("chat_fallback_not_verified_free")
    # Sin fallback implicito: la cadena Go/Groq/Gemini ya es el respaldo.
    primary = go_subscription or create_llm_provider(
        settings,
        client=client,
        reasoning_effort=settings.opencode_go_chat_reasoning_effort,
        # Un intento por modelo: un 429 del free tier no se repite (el
        # reintento duplicaba la espera); la carrera ya tiene respaldo Groq.
        max_retries=0,
        timeout_seconds=min(settings.llm_timeout_seconds, settings.chat_total_timeout_seconds),
        total_timeout_seconds=settings.chat_total_timeout_seconds,
    )
    if primary.name == GO_SUBSCRIPTION_PROVIDER:
        primary.interactive_quota_breaker = True
    elif primary.name == "opencode-go":
        primary.interactive_quota_breaker = True
        probe = LLMRequest([Message("user", "route validation")], task="chat")
        routes = (probe, replace(probe, task="main_financial_analysis"),
                  replace(probe, model=settings.opencode_go_fallback_model))
        try:
            verified = all(
                is_owner_approved_model(primary.model_router.resolve(route), settings)
                for route in routes
            )
        except (ValueError, KeyError):
            verified = False
        if not verified:
            return DisabledProvider("chat_override_not_verified_free")
    if primary.name == "disabled":
        return primary
    backup2 = _gemini_backup(settings, client)
    if backup2 is not None:
        backup2.interactive_quota_breaker = True
    if not settings.groq_chat_fallback_active:
        if backup2 is None:
            return primary
        return ChatFallbackProvider(
            primary, backup2, backup_model=GEMINI_MODEL,
            total=settings.chat_total_timeout_seconds,
            extra_backups=((backup2, GEMINI_MODEL_2),),
            settings=settings,
        )
    if primary.name not in {"opencode-go", GO_SUBSCRIPTION_PROVIDER}:
        raise ValueError("Groq chat fallback requires the verified OpenCode primary")
    backup = _groq_backup(settings, client)
    assert backup is not None  # el flag de arriba lo garantiza
    # Sin carrera: Go tiene su plazo completo y el respaldo arranca solo si
    # Go falla o lo agota (antes Groq arrancaba a los 2 s y solia ganar).
    return ChatFallbackProvider(primary, backup, total=settings.chat_total_timeout_seconds, backup2=backup2,
                                extra_backups=_openrouter_backup(settings, client), settings=settings)


def create_background_llm_provider(settings: Settings | None = None, *, client: httpx.AsyncClient | None = None) -> LLMProvider:
    """Proveedor para trabajos en segundo plano: primario con reintento
    transitorio y la cadena gratuita Groq/Gemini en secuencia.

    Reutiliza las mismas claves y flags verificados del chat. Un respaldo mal
    configurado se salta con un aviso en el log en vez de romper el trabajo:
    el primario solo ya es el comportamiento anterior.
    """
    settings = settings or get_settings()
    if current_tenant_llm_config() is not None:
        # Sin respaldos de plataforma: la clave del tenant nunca se mezcla con
        # la de GerarAI, ni siquiera cuando su proveedor falla.
        return create_llm_provider(settings, client=client, max_retries=0)
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
