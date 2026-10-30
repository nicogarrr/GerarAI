from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

from app.llm.base import (
    ADAPTER_CAPABILITIES,
    TOOL_CALLING,
    LLMProvider,
    redact_secrets,
)
from app.llm.contracts import (
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    ToolCall,
    Usage,
)
from app.llm.errors import (
    ProviderDisabledError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTransportError,
)
from app.llm.routing import TaskModelRouter

if TYPE_CHECKING:  # pragma: no cover - solo para el type checker
    from app.llm.response_cache import LLMResponseCache

logger = logging.getLogger(__name__)

#: Longitud maxima de cada campo del registro `llm.call` (un modelo legitimo
#: no pasa de unas decenas de caracteres; un cuerpo devuelto entero no cabe).
_LOG_FIELD_MAX_CHARS = 120

#: `finish_reason` que significa "respuesta completa y utilizable". Cualquier
#: otra cosa (truncado, filtro de contenido, error) marca la respuesta como
#: degradada y la cache de respuestas se niega a guardarla.
CLEAN_FINISH_REASONS = frozenset({"stop", "tool_calls", "function_call", "end_turn"})

#: Cuantos caracteres de un aviso del proveedor se conservan (ya redactados).
_WARNING_PREVIEW_CHARS = 120


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _join_text_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""


def _warning_text(value: Any, label: str) -> list[str]:
    """Normaliza `warning`/`warnings` del proveedor a texto plano y acotado."""
    if isinstance(value, str) and value.strip():
        return [f"{label}:{value.strip()}"]
    if isinstance(value, list):
        out: list[str] = []
        for item in value[:5]:
            if isinstance(item, str) and item.strip():
                out.append(f"{label}:{item.strip()}")
            elif isinstance(item, Mapping):
                message = item.get("message") or item.get("code") or item.get("type")
                if isinstance(message, str) and message.strip():
                    out.append(f"{label}:{message.strip()}")
        return out
    if isinstance(value, Mapping):
        message = value.get("message") or value.get("code")
        if isinstance(message, str) and message.strip():
            return [f"{label}:{message.strip()}"]
    return []


def parse_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    """Parseo tolerante de `choices[0].message.tool_calls`.

    Tolerante en la FORMA (que se parece al contrato OpenAI pero no tiene que
    ser identica): acepta `arguments` ya deserializado, cadena vacia (tool sin
    argumentos), `id` ausente y la variante sin envoltorio `function`. Estricto
    en lo que no se puede inventar: si `arguments` es una cadena que no es JSON
    valido, o el sobre no permite ni identificar la tool, lanza
    `ProviderResponseError`. Descartar en silencio un tool call ilegible
    haria que el caller creyera que el modelo respondio con texto.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ProviderResponseError("provider returned invalid tool calls")
    calls: list[ToolCall] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ProviderResponseError("provider returned a malformed tool call")
        function = item.get("function")
        source: Mapping[str, Any] = function if isinstance(function, Mapping) else item
        name = source.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProviderResponseError("provider returned a tool call without a name")
        raw_arguments = source.get("arguments")
        if isinstance(raw_arguments, Mapping):
            arguments: dict[str, Any] = dict(raw_arguments)
        elif raw_arguments is None or (isinstance(raw_arguments, str) and not raw_arguments.strip()):
            arguments = {}
        elif isinstance(raw_arguments, str):
            try:
                decoded = json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ProviderResponseError(
                    f"provider returned invalid JSON in the arguments of tool {name!r}"
                ) from exc
            if not isinstance(decoded, Mapping):
                raise ProviderResponseError(
                    f"provider returned non-object arguments for tool {name!r}"
                )
            arguments = dict(decoded)
        else:
            raise ProviderResponseError(
                f"provider returned unsupported arguments for tool {name!r}"
            )
        identifier = item.get("id")
        calls.append(
            ToolCall(
                id=identifier if isinstance(identifier, str) and identifier else f"call_{index}",
                name=name,
                arguments=arguments,
            )
        )
    return tuple(calls)


class DisabledProvider(LLMProvider):
    name = "disabled"
    supported_capabilities = frozenset()

    def __init__(self, reason: str = "no_provider_configured") -> None:
        self.reason = reason
        super().__init__(
            model_router=TaskModelRouter(default_model="disabled"),
            timeout_seconds=1,
            max_retries=0,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        del request
        raise ProviderDisabledError(f"LLM provider is disabled: {self.reason}")

    def __repr__(self) -> str:
        return f"DisabledProvider(reason={self.reason!r})"


class OpenAICompatibleProvider(LLMProvider):
    #: Ver ADAPTER_CAPABILITIES: lo que este adaptador REALMENTE hace.
    supported_capabilities = ADAPTER_CAPABILITIES

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        provider_name: str = "openai",
        extra_headers: Mapping[str, str] | None = None,
        model_overrides: Mapping[str, str] | None = None,
        fallback_model: str | None = None,
        strip_response_format: bool = False,
        reasoning_effort: str | None = None,
        reasoning_effort_models: frozenset[str] | set[str] | None = None,
        response_cache: LLMResponseCache | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        max_output_tokens: int = 16_000,
        total_timeout_seconds: float | None = None,
        hidden_reasoning_models: frozenset[str] | set[str] | None = None,
        hidden_reasoning_min_tokens: int = 1024,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self.name = provider_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_output_tokens = max_output_tokens
        self._total_timeout_seconds = total_timeout_seconds
        self._hidden_reasoning_models = frozenset(hidden_reasoning_models or ())
        self._hidden_reasoning_min_tokens = hidden_reasoning_min_tokens
        self._extra_headers = dict(extra_headers or {})
        # Cache de respuestas (Redis). None = sin cache. NUNCA es una via para
        # saltar la red y el presupuesto a la vez: si Redis cae, la cache
        # degrada a "no hay entrada" y se llama al proveedor normalmente
        # (fail-open). Ver app/llm/response_cache.py.
        self._response_cache = response_cache
        # Cadena de fallback: si el modelo resuelto falla en la capa LLM, se
        # reintenta una vez con este modelo (p.ej. el primario deja de
        # existir en el catalogo del proveedor). None = sin fallback.
        self._fallback_model = (fallback_model or "").strip() or None
        # Endpoints que rechazan `response_format` con HTTP 400 (verificado en
        # vivo contra /zen/go/v1 con deepseek-v4.1-flash el 2026-10-26 por el
        # piloto: json_schema estricto -> 400; json_object/plain -> 200): el
        # contrato JSON viaja en el prompt y el sobre se retira. La validacion
        # local del llamador (parse_json_response + validadores fail-closed)
        # sigue siendo la puerta; el servidor nunca fue la garantia.
        self._strip_response_format = bool(strip_response_format)
        # Nivel de razonamiento (sobre OpenAI-compatible: campo
        # `reasoning_effort`). Solo se envia a los modelos de
        # reasoning_effort_models (None = a todos); un modelo que no
        # admita el nivel configurado (p.ej. el fallback con effort=max)
        # no debe recibirlo.
        self._reasoning_effort = (reasoning_effort or "").strip() or None
        self._reasoning_effort_models = (
            frozenset(
                model.strip() for model in reasoning_effort_models if model.strip()
            )
            if reasoning_effort_models is not None
            else None
        )
        super().__init__(
            model_router=TaskModelRouter(default_model, model_overrides or {}, provider_name),
            client=client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.model_router.resolve(request)
        # El sobre se construye ANTES de tocar la red: es lo que se envia al
        # proveedor y, por tanto, exactamente lo que determina la respuesta.
        # La cache hashea ESE MISMO sobre, de modo que cualquier campo que
        # cambie la respuesta (mensajes, temperatura, max_tokens,
        # response_format, reasoning_effort, tools, tool_choice) cambia la clave
        # por construccion. Una clave por prompt seria un bug de correctitud.
        payload = self._build_payload(request, model)
        cache = self._response_cache
        cache_key: str | None = None
        if cache is not None and request.cache is not False:
            tenant_id = cache.resolve_tenant_id(request)
            if tenant_id is None and cache.require_tenant:
                # Fail closed: sin tenant no se puede garantizar aislamiento
                # entre tenants. Perder la cache es recuperable; servirle a un
                # tenant la respuesta pagada por otro no lo es. Misma politica
                # que BudgetController.current_usage sin contexto de tenant.
                cache.record_skip("no_tenant_scope")
            else:
                cache_key = cache.build_key(
                    tenant_id=tenant_id,
                    provider=self.name,
                    model=model,
                    task=request.task,
                    payload=payload,
                )
                cached = await cache.get(cache_key, model=model, task=request.task)
                if cached is not None:
                    return cached

        try:
            if self._total_timeout_seconds:
                response, used_fallback = await asyncio.wait_for(
                    self._complete_with_fallback(request, model),
                    timeout=self._total_timeout_seconds,
                )
            else:
                response, used_fallback = await self._complete_with_fallback(request, model)
        except TimeoutError:
            raise ProviderTransportError(self.name, "timeout", 1) from None

        if cache is not None and cache_key is not None:
            stored = await cache.store(
                cache_key,
                response,
                used_fallback=used_fallback,
                model=model,
                task=request.task,
            )
            if stored:
                # La clave viaja con la respuesta para que el llamador pueda
                # retirarla si la rechaza (evict_cached).
                response = replace(response, cache_key=cache_key)
        return response

    async def evict_cached(self, response: Any) -> None:
        key = getattr(response, "cache_key", None)
        if key and self._response_cache is not None:
            await self._response_cache.evict(key)

    async def _complete_with_fallback(
        self, request: LLMRequest, model: str
    ) -> tuple[LLMResponse, bool]:
        """Respaldo tardio sin interrumpir una respuesta primaria aun valida."""
        fallback = self._fallback_model
        if fallback:
            # Un override de entorno puede mapear el alias de respaldo al mismo
            # modelo del primario (LLM_MODEL_OVERRIDES): seria repetir la misma
            # llamada contra el mismo limite gratuito, no un respaldo.
            overrides = getattr(self.model_router, "overrides", None) or {}
            if overrides.get(fallback, fallback) == model:
                fallback = None
        if not fallback or fallback == model:
            return await self._complete_traced(request, model), False

        primary = asyncio.create_task(self._complete_traced(request, model))
        tasks = [primary]
        try:
            # Esperar NO cancela el primario. Si tarda mas de 2/3 del plazo,
            # lanzar respaldo en paralelo; el primario conserva hasta el final
            # los mismos 45 s que tenia antes. Fallo rapido = respaldo inmediato.
            delay = self._total_timeout_seconds * (2 / 3) if self._total_timeout_seconds else None
            done, _ = await asyncio.wait({primary}, timeout=delay)
            metadata = {"fallback_from": model}
            if done:
                try:
                    return primary.result(), False
                except Exception as exc:
                    metadata["primary_error"] = type(exc).__name__
            else:
                metadata["fallback_trigger"] = "primary_slow"

            backup = asyncio.create_task(
                self._complete_traced(request, fallback, extra_metadata=metadata)
            )
            tasks.append(backup)
            pending = {backup} | ({primary} if not done else set())
            last_error: Exception | None = None
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                # Si ambos terminan a la vez, preferir el primario valido.
                for task in tasks:
                    if task not in done:
                        continue
                    try:
                        return task.result(), task is backup
                    except Exception as exc:
                        last_error = exc
            assert last_error is not None
            raise last_error
        finally:
            # Recoger errores y cancelaciones tambien al cancelar el caller o
            # al agotarse el limite exterior. Ninguna generacion queda suelta.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def effective_reasoning_effort(self, request: LLMRequest, model: str) -> str | None:
        """Nivel de razonamiento que de verdad viaja en el sobre (None = no se envia)."""
        effort = request.reasoning_effort or self._reasoning_effort
        if effort and (
            self._reasoning_effort_models is None
            or model in self._reasoning_effort_models
        ):
            return effort
        return None

    def _log_call(
        self,
        request: LLMRequest,
        model: str,
        *,
        status: str,
        duration_ms: int,
        response: LLMResponse | None = None,
        error: str | None = None,
        extra_metadata: Mapping[str, str] | None = None,
    ) -> None:
        """Una linea por llamada: proveedor, modelo, razonamiento y clave usados.

        Permite comprobar en los logs de Render/Oracle que cada llamada fue a
        OpenCode Go con DeepSeek V4.1 Flash y el nivel esperado. Nunca se
        registran prompts, respuestas ni la clave; solo su ambito
        (plataforma o tenant).
        """
        host = urlsplit(self._base_url).hostname or "?"
        fallback_from = (extra_metadata or {}).get("fallback_from")
        level = logging.WARNING if status == "failed" else logging.INFO
        safe = self._redact_for_log
        logger.log(
            level,
            "llm.call provider=%s model=%s requested_model=%s reasoning_effort=%s "
            "task=%s status=%s duration_ms=%d host=%s key_scope=%s fallback_from=%s "
            "output_tokens=%s reasoning_tokens=%s error=%s",
            safe(self.name),
            safe(response.model if response is not None else model),
            safe(model),
            safe(self.effective_reasoning_effort(request, model) or "none_sent"),
            safe(request.task or "-"),
            status,
            duration_ms,
            safe(host),
            safe(getattr(self, "billing_scope", "platform")),
            safe(fallback_from or "-"),
            response.usage.output_tokens if response is not None else "-",
            response.usage.reasoning_tokens if response is not None else "-",
            safe(error or "-"),
        )

    def _recorded_model(self, body_model: Any, requested_model: str) -> str:
        """Modelo que viaja en ``LLMResponse.model``.

        A diferencia del registro `llm.call` (que ya redacta), este valor se
        PERSISTE (budget_usage, telemetria del chat) y se devuelve al frontend
        (ChatResponse.model), y lo controla el proveedor: un endpoint custom
        de tenant podria devolver en `body["model"]` la propia clave, un
        `sk-...` o una cadena de miles de caracteres que romperia el insert
        (String(160)). Mismas reglas que los avisos (`_collect_warnings`):
        redaccion con la key y las cabeceras conocidas, espacios normalizados
        y cota de longitud. Si el proveedor no manda modelo (o queda vacio),
        se conserva el pedido, como antes.
        """
        if not isinstance(body_model, str):
            return requested_model
        known = [str(self._api_key or "")]
        known.extend(str(v) for v in self._extra_headers.values())
        text = redact_secrets(body_model, known)
        text = " ".join(text.split())[:160]
        return text or requested_model

    def _redact_for_log(self, value: object) -> str:
        """Texto apto para el registro `llm.call` y las trazas.

        Todos los campos de texto pasan por aqui, no solo el error: el modelo
        lo devuelve el proveedor (`body["model"]`) y el modelo pedido o la
        tarea pueden venir de Ajustes, asi que cualquiera de ellos podria
        contener una clave. Se redactan la key y las cabeceras conocidas, los
        patrones habituales (`sk-…`, `Bearer …`, `api_key=…`), y se quitan
        espacios y saltos de linea para que un valor no pueda inyectar
        campos falsos (`status=ok`) en la linea.
        """
        known = [str(self._api_key or "")]
        known.extend(str(v) for v in self._extra_headers.values())
        text = redact_secrets(str(value), known)
        text = "_".join(text.split())
        return text[:_LOG_FIELD_MAX_CHARS] if text else "-"

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        """Sobre OpenAI-compatible. Unico lugar que decide que se envia."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.to_openai() for message in request.messages],
        }
        # El override de la request gana al default del proveedor (p. ej. una
        # ruta estructurada larga pide "none" sin tocar al chat). El filtro de
        # modelos soportados se aplica igual en ambos casos.
        effort = self.effective_reasoning_effort(request, model)
        if effort:
            payload["reasoning_effort"] = effort
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            requested = request.max_tokens
            if model in self._hidden_reasoning_models:
                # El razonamiento oculto consume parte del presupuesto: un
                # max_tokens bajo deja la respuesta vacia.
                requested = max(requested, self._hidden_reasoning_min_tokens)
            payload["max_tokens"] = min(
                requested,
                self._max_output_tokens,
            )
        if request.response_format is not None and self._strip_response_format:
            # Mismo tratamiento probado en el chat (GoSubscriptionChatProvider):
            # sobre fuera, contrato en el ultimo mensaje de usuario.
            response_format = request.response_format
            instruction = (
                "Responde SOLO con un objeto JSON valido, sin texto fuera del "
                "JSON ni bloque de codigo."
            )
            if response_format.type == "json_schema" and response_format.schema:
                instruction += " Debe cumplir este esquema JSON: " + json.dumps(
                    dict(response_format.schema), ensure_ascii=False, sort_keys=True
                )
            messages = payload["messages"]
            last = messages[-1] if messages else None
            if last and last.get("role") == "user" and isinstance(last.get("content"), str):
                last["content"] = f"{last['content']}\n\n{instruction}"
            else:
                messages.append({"role": "user", "content": instruction})
        elif request.response_format is not None:
            response_format = request.response_format
            if response_format.type == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_format.name,
                        "strict": response_format.strict,
                        "schema": dict(response_format.schema or {}),
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}
        if request.tools:
            # Las tools solo viajan si la capacidad esta IMPLEMENTADA por este
            # adaptador. Declararlas sin enviarlas era exactamente el defecto
            # que hacia falsa la configuracion.
            if TOOL_CALLING not in self.supported_capabilities:
                raise ProviderRequestError(
                    f"{self.name} adapter does not implement tool calling"
                )
            payload["tools"] = [tool.to_openai() for tool in request.tools]
            payload["tool_choice"] = self._tool_choice_payload(request)
        return payload

    def _tool_choice_payload(self, request: LLMRequest) -> Any:
        choice = request.tool_choice
        if choice is None:
            return "auto"
        if isinstance(choice, str):
            return choice
        function = choice.get("function")
        source: Mapping[str, Any] = function if isinstance(function, Mapping) else choice
        return {
            "type": "function",
            "function": {"name": source.get("name")},
        }

    async def _complete_traced(
        self,
        request: LLMRequest,
        model: str,
        extra_metadata: Mapping[str, str] | None = None,
    ) -> LLMResponse:
        # Stage 3: generation span sobre la traza activa (si la hay). Solo
        # metadatos y contadores; prompts y completaciones jamas salen.
        import time as _time

        from app.services import tracing as _tracing

        _started = _time.monotonic()
        try:
            response = await self._complete(request, model)
        except (Exception, asyncio.CancelledError) as exc:
            cancelled = isinstance(exc, asyncio.CancelledError)
            self._log_call(
                request,
                model,
                status="cancelled" if cancelled else "failed",
                duration_ms=int((_time.monotonic() - _started) * 1000),
                error=None if cancelled else type(exc).__name__,
                extra_metadata=extra_metadata,
            )
            _tracing.trace_generation(
                name=f"llm.{request.task or 'complete'}",
                model=self._redact_for_log(model),
                metadata={
                    "provider": self.name,
                    "task": request.task,
                    "route": self._redact_for_log(model),
                    "duration_ms": int((_time.monotonic() - _started) * 1000),
                    **dict(request.metadata or {}),
                    **dict(extra_metadata or {}),
                    "status": "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                },
                # La tarea perdedora se cancela tambien en corridas exitosas:
                # conservar su span sin marcar toda la corrida como fallo.
                error_class=None if isinstance(exc, asyncio.CancelledError) else type(exc).__name__,
            )
            raise
        self._log_call(
            request,
            model,
            status="ok",
            duration_ms=int((_time.monotonic() - _started) * 1000),
            response=response,
            extra_metadata=extra_metadata,
        )
        _tracing.trace_generation(
            name=f"llm.{request.task or 'complete'}",
            model=self._redact_for_log(response.model),
            metadata={
                "provider": self.name,
                "task": request.task,
                "route": self._redact_for_log(model),
                "duration_ms": int((_time.monotonic() - _started) * 1000),
                **dict(request.metadata or {}),
                **dict(extra_metadata or {}),
            },
            usage={
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
                "total": response.usage.total_tokens,
                "cache_read": response.usage.cache_read_tokens,
                "reasoning": response.usage.reasoning_tokens,
            },
        )
        return response

    async def _complete(self, request: LLMRequest, model: str) -> LLMResponse:
        payload = self._build_payload(request, model)

        response = await self._post_json(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                **self._extra_headers,
            },
            payload=payload,
        )
        body = self._response_json(response)
        try:
            choice = body["choices"][0]
            assistant = choice["message"]
            content = _join_text_blocks(assistant["content"])
        except (KeyError, IndexError, TypeError):
            raise ProviderResponseError(f"{self.name} returned no assistant message") from None
        tool_calls = parse_tool_calls(assistant.get("tool_calls"))
        if not content and not tool_calls:
            raise ProviderResponseError(f"{self.name} returned an empty assistant message")

        if self._strip_response_format and request.response_format is not None:
            # El modelo a veces envuelve el JSON en un bloque ```: se desenvuelve
            # para que los validadores locales vean el JSON puro.
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else ""
                content = content.rsplit("```", 1)[0].strip()

        usage_body = body.get("usage")
        if not isinstance(usage_body, dict):
            raise ProviderResponseError(f"{self.name} returned missing token usage")
        raw_input_tokens = usage_body.get("prompt_tokens")
        raw_output_tokens = usage_body.get("completion_tokens")
        if not isinstance(raw_input_tokens, int) or raw_input_tokens < 0:
            raise ProviderResponseError(f"{self.name} returned invalid prompt token usage")
        if not isinstance(raw_output_tokens, int) or raw_output_tokens < 0:
            raise ProviderResponseError(f"{self.name} returned invalid completion token usage")
        input_tokens = raw_input_tokens
        output_tokens = raw_output_tokens
        prompt_details = usage_body.get("prompt_tokens_details") or {}
        prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
        completion_details = usage_body.get("completion_tokens_details") or {}
        completion_details = (
            completion_details if isinstance(completion_details, dict) else {}
        )
        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=_integer(usage_body.get("total_tokens")) or input_tokens + output_tokens,
            cache_read_tokens=_integer(prompt_details.get("cached_tokens")),
            reasoning_tokens=_integer(completion_details.get("reasoning_tokens")),
        )
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        warnings = self._collect_warnings(body)
        degraded = bool(warnings) or (
            finish_reason is not None and finish_reason not in CLEAN_FINISH_REASONS
        )
        return LLMResponse(
            message=Message(MessageRole.ASSISTANT, content),
            usage=usage,
            model=self._recorded_model(body.get("model"), model),
            provider=self.name,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            request_id=body.get("id") if isinstance(body.get("id"), str) else None,
            tool_calls=tool_calls,
            degraded=degraded,
            warnings=warnings,
        )

    def _collect_warnings(self, body: Mapping[str, Any]) -> tuple[str, ...]:
        """Avisos del proveedor, redactados con las mismas reglas que los logs.

        Un aviso nunca debe poder introducir una credencial en la salida que
        los flujos narrativos guardan en Postgres, asi que pasa por
        `redact_secrets` con la key y las cabeceras conocidas.
        """
        raw: list[str] = []
        for key in ("warning", "warnings"):
            if key in body:
                raw.extend(_warning_text(body.get(key), key))
        if not raw:
            return ()
        known = [str(self._api_key or "")]
        known.extend(str(value) for value in self._extra_headers.values())
        return tuple(
            redact_secrets(text, known)[:_WARNING_PREVIEW_CHARS] for text in raw[:5]
        )

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleProvider(provider_name={self.name!r}, "
            f"base_url={self._base_url!r})"
        )
