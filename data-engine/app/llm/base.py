from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

import httpx

from app.llm.contracts import LLMRequest, LLMResponse, ResponseFormat
from app.llm.errors import LLMError, ProviderHTTPError, ProviderResponseError, ProviderTransportError
from app.llm.json import parse_json_response
from app.llm.run_guard import reserve_request

logger = logging.getLogger(__name__)

# OpenCode answers 502 with this fixed message when its free tier is used from outside
# OpenCode. It does not change between attempts, so retrying only burns seconds.
_FREE_TIER_ORIGIN_MARKERS = (
    "free tier can only be used from within",
    # Same deterministic 502 when OpenCode blocks the egress IP of the server.
    "free models aren't available from your current network",
    "abusive traffic from this ip",
)
_FREE_TIER_BREAKER_SECONDS = 120.0
# Existing origin breaker (all flows). After expiry the next call is a real probe.
_free_tier_breaker: dict[tuple[str, str], float] = {}
_free_tier_breaker_status: dict[tuple[str, str], int] = {}
# Quota state is shared ONLY by opted-in interactive providers (chat/debate).
# Background providers neither read nor write it.
_interactive_quota_breaker: dict[tuple[str, str], float] = {}
# Cuota gratuita agotada (429 con senal de cuota en el cuerpo, p.ej.
# "weekly exhausted"): un presupuesto semanal/diario no vuelve con el backoff
# de 0,75 s del reintento, y sin breaker cada item de un lote reintentaba 3
# veces contra un proveedor agotado y el siguiente item volvia a sondearlo
# (hallazgo de prod: minutos de 429 "weekly exhausted" en worker-default
# desde jev_fallback). Mismo patron que el breaker de origen 502: cooldown
# por (proveedor, modelo) y una sonda real al expirar. Los proveedores
# interactivos (chat/debate) usan su propio breaker de arriba.
_free_quota_breaker: dict[tuple[str, str], float] = {}
_QUOTA_429_BODY_MARKERS = ("exhausted", "quota", "insufficient credit", "billing")


def _is_free_tier_origin_error(response: httpx.Response) -> bool:
    if response.status_code != 502:
        return False
    try:
        text = response.text.lower()
        return any(marker in text for marker in _FREE_TIER_ORIGIN_MARKERS)
    except Exception:
        return False

def _is_quota_exhausted_429(response: httpx.Response) -> bool:
    """429 con senal explicita de cuota agotada en el cuerpo (no rate limit).

    Un "rate limit" plano puede recuperarse en segundos y conserva sus
    reintentos; "weekly exhausted"/"insufficient_quota" no, asi que se corta
    el reintento y se abre el breaker en vez de seguir llamando.
    """
    if response.status_code != 429:
        return False
    try:
        text = response.text.lower()
        return any(marker in text for marker in _QUOTA_429_BODY_MARKERS)
    except Exception:
        return False


_ERROR_BODY_PREVIEW_CHARS = 200
_REDACTED = "[REDACTED]"
_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"),
    re.compile(
        r"(?i)((?:api[_-]?key|x-api-key|authorization|token|secret)[\"']?\s*[:=]\s*[\"']?)"
        r"[^\s\"',;}&]+"
    ),
    re.compile(r"(?i)(incorrect api key provided:\s*)\S+"),
    re.compile(r"(?i)(invalid api key:?\s*)\S+"),
)


def redact_secrets(text: str, known_secrets: Sequence[str] = ()) -> str:
    """Quita credenciales conocidas y patrones habituales antes de truncar o loguear."""
    for secret in sorted({str(x) for x in known_secrets if x}, key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + _REDACTED, text)
        else:
            text = pattern.sub(_REDACTED, text)
    return text


#: Capacidades que los adaptadores de ESTA app implementan de verdad.
#:
#: El registro de aliases (`app/llm/model_aliases.py`) declara lo que el
#: MODELO soporta; este conjunto declara lo que el CODIGO hace. Los dos deben
#: quedar en correspondencia: `tests/test_llm_tool_calling.py` falla si
#: un alias activo afirma una capacidad que no esta aqui, y falla tambien si
#: esta lista afirma algo que el adaptador dejo de enviar.
#:
#: - ``text``: toda respuesta pasa por aqui.
#: - ``structured_output``: ``ResponseFormat`` viaja como ``response_format``
#:   (``json_object`` y ``json_schema`` con ``strict``).
#: - ``reasoning``: ``reasoning_effort`` se reenvia al proveedor, pero SOLO
#:   para los modelos de ``reasoning_effort_models``. Es una capacidad del
#:   adaptador con alcance por modelo, no del canal.
#: - ``tool_calling``: ``tools``/``tool_choice`` se envian cuando la peticion
#:   los trae, y ``choices[0].message.tool_calls`` se parsea y valida.
#:
#: Lo que NO esta aqui y por tanto nadie puede afirmar: multimodalidad
#: (el adaptador no serializa adjuntos), batching, streaming y cache de
#: prompts en el proveedor.
ADAPTER_CAPABILITIES: frozenset[str] = frozenset(
    {"text", "structured_output", "reasoning", "tool_calling"}
)

#: Alias de la capacidad de tool calling, usada por las rutas y los tests.
TOOL_CALLING = "tool_calling"


class ModelRouter(Protocol):
    """Lo unico que el resto del codigo exige de un router: resolver el modelo de una peticion."""

    def resolve(self, request: LLMRequest) -> str: ...


class LLMProvider(ABC):
    name: str
    #: Quien paga las llamadas: "platform" (GerarAI) o "tenant" (clave propia).
    billing_scope: str = "platform"
    #: Lo que ESTE adaptador implementa. Vacio por defecto: un adaptador que no
    #: lo declare no puede afirmar ninguna capacidad (fail closed).
    supported_capabilities: frozenset[str] = frozenset()
    #: True para destinos elegidos por un usuario (proveedor ``custom``): la
    #: conexion solo se abre a IPs publicas validadas al conectar y se ignora
    #: cualquier cliente HTTP inyectado (ver app/llm/egress_guard.py).
    public_only: bool = False

    def __init__(
        self,
        *,
        model_router: ModelRouter,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.model_router = model_router
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    async def generate_json(
        self,
        request: LLMRequest,
        *,
        schema: Mapping[str, Any] | None = None,
        schema_name: str = "response",
    ) -> Any:
        response_format = (
            ResponseFormat.json_schema(schema, name=schema_name)
            if schema is not None
            else ResponseFormat.json_object()
        )
        response = await self.complete(replace(request, response_format=response_format))
        return parse_json_response(response.text)

    async def _post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> httpx.Response:
        breaker_key = (str(self.name), str(payload.get("model")))
        if _free_tier_breaker.get(breaker_key, 0.0) > time.monotonic():
            raise ProviderHTTPError(self.name, _free_tier_breaker_status.get(breaker_key, 502))
        if _free_quota_breaker.get(breaker_key, 0.0) > time.monotonic():
            raise ProviderHTTPError(self.name, 429)
        interactive_quota = getattr(self, "interactive_quota_breaker", False)
        if interactive_quota and _interactive_quota_breaker.get(breaker_key, 0.0) > time.monotonic():
            raise ProviderHTTPError(self.name, 429)
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._send(url, headers=headers, payload=payload)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    # Persist only a fixed category, never the exception message,
                    # request URL, headers or body. Jobs expose this text to users.
                    categories = ((httpx.ReadTimeout, "read_timeout"), (httpx.ConnectTimeout, "connect_timeout"),
                                  (httpx.WriteTimeout, "write_timeout"), (httpx.PoolTimeout, "pool_timeout"),
                                  (httpx.TimeoutException, "timeout"), (httpx.ConnectError, "connect_error"),
                                  (httpx.ProtocolError, "protocol_error"))
                    reason = next((label for kind, label in categories if isinstance(exc, kind)), "transport_error")
                    raise ProviderTransportError(self.name, reason, attempt + 1) from None
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            if response.status_code < 400:
                return response
            self._log_http_error(response, headers, payload, attempt)
            if interactive_quota and response.status_code == 429:
                _interactive_quota_breaker[breaker_key] = time.monotonic() + _FREE_TIER_BREAKER_SECONDS
                raise ProviderHTTPError(self.name, 429)
            if _is_quota_exhausted_429(response):
                _free_quota_breaker[breaker_key] = time.monotonic() + _FREE_TIER_BREAKER_SECONDS
                raise ProviderHTTPError(self.name, 429)
            if _is_free_tier_origin_error(response):
                _free_tier_breaker_status[breaker_key] = 502
                _free_tier_breaker[breaker_key] = time.monotonic() + _FREE_TIER_BREAKER_SECONDS
                raise ProviderHTTPError(self.name, 502)
            if response.status_code not in {408, 409, 429} and response.status_code < 500:
                raise ProviderHTTPError(self.name, response.status_code)
            if attempt >= self._max_retries:
                raise ProviderHTTPError(self.name, response.status_code)
            await asyncio.sleep(0.25 * (2**attempt))

        raise LLMError(f"{self.name} request failed")

    def _log_http_error(
        self,
        response: httpx.Response,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        attempt: int,
    ) -> None:
        """Deja evidencia del rechazo (estado, modelo, inicio del cuerpo) sin credenciales."""
        known = [str(getattr(self, "_api_key", "") or "")]
        try:
            for value in headers.values():
                value = str(value)
                known.append(value)
                parts = value.split(None, 1)
                if len(parts) == 2 and parts[0].lower() in {"bearer", "basic", "token"}:
                    known.append(parts[1])
            body = redact_secrets(response.text, known)[:_ERROR_BODY_PREVIEW_CHARS]
        except Exception:  # pragma: no cover - cuerpo ilegible
            body = "<unreadable>"
        logger.warning(
            "LLM provider %s HTTP %s model=%s attempt=%s body=%r",
            redact_secrets(str(self.name), known),
            response.status_code,
            redact_secrets(str(payload.get("model")), known),
            attempt + 1,
            body,
        )

    async def _send(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> httpx.Response:
        # Tope duro por corrida (inactivo salvo que haya un guard en el
        # contexto): reserva cupo ANTES de la red; ver app/llm/run_guard.py.
        reserve_request(url, payload, guard_required=bool(getattr(self, "guard_required", False)))
        if self.public_only:
            from app.llm.egress_guard import public_only_client

            async with public_only_client(self._timeout) as guarded:
                return await guarded.post(url, headers=dict(headers), json=dict(payload))
        if self._client is not None:
            return await self._client.post(
                url,
                headers=dict(headers),
                json=dict(payload),
                timeout=self._timeout,
            )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(url, headers=dict(headers), json=dict(payload))

    def _response_json(self, response: httpx.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            raise ProviderResponseError(f"{self.name} returned a non-JSON response") from None
        if not isinstance(payload, dict):
            raise ProviderResponseError(f"{self.name} returned an invalid response envelope")
        return payload
