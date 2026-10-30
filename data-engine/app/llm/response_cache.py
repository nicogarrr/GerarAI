"""Stage 5: cache de respuestas LLM en Redis.

Por que existe: el backend ya tiene topes por tenant (``BudgetController``,
cuotas por feature con Lua atomico) pero NO memoizaba ninguna completacion.
Con el proveedor en un modelo gratuito pero TOPE DE CANTIDAD por suscripcion,
cada pregunta identica repetida es presupuesto y cuota quemados para nada.

Reglas duras (todas verificables en tests/test_response_cache*.py):

1. **La clave es el hash del SOBRE, no del prompt.** Se hashea el mismo dict
   que se envia al proveedor (modelo, mensajes, temperatura, max_tokens,
   ``response_format``, ``reasoning_effort``, ``tools``, ``tool_choice``) mas
   tenant, proveedor y tarea. Todo lo que puede cambiar la respuesta esta en la
   clave POR CONSTRUCCION, no por memoria: anadir un campo al sobre cambia la
   clave sin tocar este modulo. Una clave "solo prompt" seria un bug de
   correctitud, no una optimizacion.

2. **Aislamiento por tenant.** El tenant se resuelve del contexto
   (``tenant_cache_scope``) o de ``LLMRequest.metadata["tenant_id"]``. Sin
   tenant, la politica por defecto es **fail closed**: no se lee ni se escribe
   cache (``require_tenant=True``), igual que ``BudgetController.current_usage``
   que se niega a agregar sin contexto de tenant. Con
   ``LLM_RESPONSE_CACHE_REQUIRE_TENANT=false`` las peticiones sin tenant
   comparten el namespace ``unscoped`` (solo tiene sentido en despliegues sin
   multitenant).

3. **Presupuesto: un acierto de cache cuesta 0.** La respuesta servida desde
   cache se devuelve con ``from_cache=True`` y con ``usage`` a cero
   (``cache_read_tokens`` acumula los tokens evitados). Como
   ``BudgetController.record`` calcula el coste desde ``response.usage``, la
   fila que escriben los servicios existentes sale a 0.00 EUR: el presupuesto se
   cobro una vez, la primera vez. Los contadores de tokens que se exponen en las
   respuestas de la API pasan a 0 tambien, que es la lectura honesta: no se
   consumio ningun token en esa llamada. (Los servicios que validan calidad
   sobre texto siguen viendo el mismo texto.)

4. **Fail-open.** Si Redis no esta, falla o devuelve basura, la cache se
   degrada a "no hay entrada" y la llamada va al proveedor como si no existiera.
   Nunca 500 por una cache.

5. **TTL con cota dura.** Redis ``SET ... EX ttl`` mas un indice ZSET por
   namespace escrito con un unico script Lua atomico: borra lo caducado por TTL
   y, si el cardinal sigue por encima de ``max_entries``, DEL + ZREM de las
   entradas mas antiguas. El recorte es **FIFO por escritura**, no LRU: el TTL
   es uniforme, asi que el score ES la fecha de escritura y `score + ttl` es la
   caducidad real. Un acierto NO refresca el score a proposito: si lo hiciera,
   score y TTL se desincronizarian y el recorte dejaria de ser exacto.

6. **Que NO se cachea jamas.**
   - Respuestas con ``degraded=True`` o con ``warnings`` del proveedor.
   - ``finish_reason`` fuera de {stop, tool_calls, function_call, end_turn}
     (truncado por ``length``, ``content_filter``, ...).
   - Respuestas obtenidas por el camino de **fallback de modelo**.
   - Peticiones marcadas con ``LLMRequest.cache=False`` (dato efimero).
   - Todo fallo: una excepcion nunca deja entrada.

7. **Sin secretos ni prompts en la instrumentacion.** Solo contadores
   agregados (hits/misses/writes/skips/errors), modelo, tarea y el hash de la
   clave. Los avisos del proveedor se guardan ya redactados por el adaptador.

Configuracion: los valores salen de ``LLM_RESPONSE_CACHE_*`` en el entorno con
los mismos nombres y limites que tendrian como campos de
``app/core/config.py::Settings`` (que no es editable en este cambio). Si un dia
se anaden esos campos a ``Settings``, tienen prioridad automatically: el valor
de ``Settings`` gana sobre el entorno. Redis sale de ``Settings.redis_url``.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import Settings, get_settings
from app.llm.contracts import LLMRequest, LLMResponse, Message, MessageRole, ToolCall, Usage

logger = logging.getLogger(__name__)

KEY_PREFIX = "cavaai:llm-response-cache"
#: Version del sobre serializado. Cambiarla invalida las entradas viejas en
#: lugar de intentar migrarlas: una respuesta guardada con otro formato de
#: `usage` cobraria presupuesto equivocado.
SCHEMA_VERSION = 1

#: Namespace para peticiones sin tenant identificable (ver regla 2).
UNSCOPED_TENANT = "unscoped"

ENV_PREFIX = "LLM_RESPONSE_CACHE_"

#: `finish_reason` que significa "esto esta entero". Cualquier otro valor es
#: una respuesta incompleta o filtrada: cachear eso congelaria el defecto.
CLEAN_FINISH_REASONS = frozenset({"stop", "tool_calls", "function_call", "end_turn"})

# ---------------------------------------------------------------------------
# Redis: escritura acotada atomica
# ---------------------------------------------------------------------------

# KEYS[1] = clave de la entrada, KEYS[2] = indice ZSET del namespace
# ARGV[1] = valor, ARGV[2] = ttl s, ARGV[3] = score (epoch ms, monotono), ARGV[4] = max entradas
_STORE_SCRIPT = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('ZADD', KEYS[2], ARGV[3], KEYS[1])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', tonumber(ARGV[3]) - tonumber(ARGV[2]) * 1000)
local count = redis.call('ZCARD', KEYS[2])
local max_entries = tonumber(ARGV[4])
if count > max_entries then
  local victims = redis.call('ZRANGE', KEYS[2], 0, count - max_entries - 1)
  for i = 1, #victims do
    redis.call('DEL', victims[i])
    redis.call('ZREM', KEYS[2], victims[i])
  end
end
return 1
"""

# Bypass de lectura cuando el tenant no es resoluble con la politica estricta.
_TENANT_SCOPE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cavaai_llm_cache_tenant", default=None
)


@contextmanager
def tenant_cache_scope(tenant_id: int | str | None) -> Iterator[str | None]:
    """Fija el tenant de la cache para el bloque (request, job, tarea).

    Es el punto de enganche que falta para que la cache sirva en produccion:
    los servicios que llaman al proveedor deben entrar aqui con el tenant
    verificado. Sin el, la cache falla cerrada y no memoiza nada.
    """
    scoped = None if tenant_id is None else str(tenant_id)
    token = _TENANT_SCOPE.set(scoped)
    try:
        yield scoped
    finally:
        _TENANT_SCOPE.reset(token)


def current_cache_tenant() -> str | None:
    return _TENANT_SCOPE.get()


def resolve_tenant_id(request: LLMRequest | None = None) -> str | None:
    """Tenant del contexto o de los metadatos de la peticion. None si no hay."""
    scoped = _TENANT_SCOPE.get()
    if scoped:
        return scoped
    metadata = getattr(request, "metadata", None) or {}
    for key in ("tenant_id", "tenant"):
        value = metadata.get(key)
        if value:
            return str(value)
    return None


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------


def _env(name: str) -> str | None:
    raw = os.environ.get(ENV_PREFIX + name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _setting(settings: Settings, name: str) -> Any:
    """Un campo de Settings si existe; None todavia (ver docstring del modulo)."""
    return getattr(settings, name, None)


def _bool_value(settings: Settings, name: str, env_name: str, default: bool) -> bool:
    override = _setting(settings, name)
    if isinstance(override, bool):
        return override
    raw = _env(env_name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int_value(
    settings: Settings,
    name: str,
    env_name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    override = _setting(settings, name)
    if isinstance(override, int) and not isinstance(override, bool):
        return max(minimum, min(maximum, override))
    raw = _env(env_name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "llm response cache: %s%s ignorado (no es un entero)",
            ENV_PREFIX,
            env_name,
        )
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class CacheSettings:
    enabled: bool = True
    ttl_seconds: int = 900
    max_entries: int = 500
    require_tenant: bool = True
    log_every: int = 50
    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout: float = 0.25
    redis_socket_timeout: float = 0.5


def load_cache_settings(settings: Settings | None = None) -> CacheSettings:
    settings = settings or get_settings()
    return CacheSettings(
        enabled=_bool_value(settings, "llm_response_cache_enabled", "ENABLED", True),
        ttl_seconds=_int_value(
            settings,
            "llm_response_cache_ttl_seconds",
            "TTL_SECONDS",
            900,
            minimum=1,
            maximum=86_400,
        ),
        max_entries=_int_value(
            settings,
            "llm_response_cache_max_entries",
            "MAX_ENTRIES",
            500,
            minimum=1,
            maximum=1_000_000,
        ),
        require_tenant=_bool_value(
            settings, "llm_response_cache_require_tenant", "REQUIRE_TENANT", True
        ),
        log_every=_int_value(
            settings, "llm_response_cache_log_every", "LOG_EVERY", 50, minimum=1, maximum=10_000
        ),
        redis_url=settings.redis_url,
    )


# ---------------------------------------------------------------------------
# Serializacion
# ---------------------------------------------------------------------------


def encode_response(response: LLMResponse) -> str:
    return json.dumps(
        {
            "v": SCHEMA_VERSION,
            "content": response.message.content,
            "model": response.model,
            "provider": response.provider,
            "finish_reason": response.finish_reason,
            "request_id": response.request_id,
            "degraded": response.degraded,
            "warnings": list(response.warnings),
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
                "cache_read_tokens": response.usage.cache_read_tokens,
                "cache_write_tokens": response.usage.cache_write_tokens,
            },
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
                for call in response.tool_calls
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def decode_response(blob: str | bytes) -> LLMResponse:
    if isinstance(blob, bytes):
        blob = blob.decode("utf-8")
    raw = json.loads(blob)
    if not isinstance(raw, dict) or raw.get("v") != SCHEMA_VERSION:
        raise ValueError("unsupported cached response envelope")
    usage = raw.get("usage") or {}
    return LLMResponse(
        message=Message(MessageRole.ASSISTANT, raw.get("content") or ""),
        usage=Usage(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_tokens") or 0),
            cache_write_tokens=int(usage.get("cache_write_tokens") or 0),
        ),
        model=str(raw.get("model") or ""),
        provider=str(raw.get("provider") or ""),
        finish_reason=raw.get("finish_reason"),
        request_id=raw.get("request_id"),
        tool_calls=tuple(
            ToolCall(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                arguments=dict(item.get("arguments") or {}),
            )
            for item in raw.get("tool_calls") or []
            if isinstance(item, dict)
        ),
        degraded=bool(raw.get("degraded")),
        warnings=tuple(str(item) for item in raw.get("warnings") or []),
    )


def is_cacheable(response: LLMResponse, *, used_fallback: bool = False) -> bool:
    """Regla 6. Un "no" aqui es siempre un acierto de diseno."""
    if used_fallback:
        return False
    if response.degraded or response.warnings:
        return False
    if response.finish_reason is not None and response.finish_reason not in CLEAN_FINISH_REASONS:
        return False
    return True


def as_cached(response: LLMResponse, key: str) -> LLMResponse:
    """Marca la respuesta como servida desde cache y pone el uso a cero.

    `usage` a cero es lo que hace que el presupuesto NO se cobre dos veces:
    `BudgetController.record` deriva el coste de `response.usage`, asi que la
    fila sale a 0.00 EUR y el tope diario/mensual del tenant queda intacto.
    `cache_read_tokens` acumula los tokens evitados para que la observabilidad
    vea el ahorro sin inventarse gasto.
    """
    avoided = response.usage.input_tokens + response.usage.output_tokens
    return replace(
        response,
        usage=Usage(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cache_read_tokens=avoided,
            cache_write_tokens=response.usage.cache_write_tokens,
        ),
        from_cache=True,
        cache_key=key,
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class LLMResponseCache:
    def __init__(
        self,
        *,
        ttl_seconds: int = 900,
        max_entries: int = 500,
        require_tenant: bool = True,
        namespace: str = "default",
        log_every: int = 50,
        connect_timeout: float = 0.25,
        socket_timeout: float = 0.5,
        redis_factory=None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if log_every <= 0:
            raise ValueError("log_every must be positive")
        self.ttl_seconds = int(ttl_seconds)
        self.max_entries = int(max_entries)
        self.require_tenant = bool(require_tenant)
        self.log_every = int(log_every)
        self.connect_timeout = float(connect_timeout)
        self.socket_timeout = float(socket_timeout)
        # Namespace por despliegue/proveedor: dos despliegues que compartan
        # Redis no pueden servirse el uno el sobre del otro aunque coincida
        # todo lo demas.
        self.namespace = f"{KEY_PREFIX}:{namespace}"
        self._index_key = f"{self.namespace}:index"
        self._redis_factory = redis_factory
        self._client: Any | None = None
        # Si la CONSTRUCCION del cliente falla (no el uso), la cache queda
        # apagada para este provider en vez de reintentar en cada llamada. Los
        # fallos de uso si son reintentables: solo cuentan como error.
        self._client_failed = False
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._operations = 0
        self._last_score = 0

    def _next_score(self) -> int:
        """Score del indice ZSET: epoch en ms, estrictamente creciente.

        La monotonia dentro del proceso no es un detalle: `ZRANGE` ordena por
        score y, a igual score, por clave. Con la misma marca de milisegundo
        para dos escrituras, "la mas antigua" seria arbitraria y el recorte
        FIFO dejaria de ser FIFO. El bump de 1 ms no altera la caducidad
        (score + ttl ~= ahora + ttl, con deriva de milisegundos).
        """
        with self._lock:
            score = int(time.time() * 1000)
            if score <= self._last_score:
                score = self._last_score + 1
            self._last_score = score
            return score

    # -- clave ------------------------------------------------------------

    def resolve_tenant_id(self, request: LLMRequest | None = None) -> str | None:
        return resolve_tenant_id(request)

    def build_key(
        self,
        *,
        tenant_id: str | None,
        provider: str,
        model: str,
        task: str | None,
        payload: Mapping[str, Any],
    ) -> str:
        canonical = json.dumps(
            {
                "v": SCHEMA_VERSION,
                "tenant": tenant_id or UNSCOPED_TENANT,
                "provider": provider,
                "model": model,
                "task": task or "",
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self.namespace}:e:{digest[:40]}"

    # -- instrumentacion ---------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def reset_stats(self) -> None:
        with self._lock:
            self._counters.clear()
            self._operations = 0

    def record_skip(self, reason: str) -> None:
        self._count("skip")
        logger.debug("llm response cache bypass reason=%s", reason)

    def _count(self, outcome: str) -> None:
        with self._lock:
            self._counters[outcome] = self._counters.get(outcome, 0) + 1
            self._operations += 1
            operations = self._operations
            snapshot = dict(self._counters)
        if operations % self.log_every == 0:
            logger.info(
                "llm response cache hits=%d misses=%d writes=%d skips=%d errors=%d",
                snapshot.get("hit", 0),
                snapshot.get("miss", 0),
                snapshot.get("write", 0),
                snapshot.get("skip", 0),
                snapshot.get("error", 0),
            )

    @staticmethod
    def _trace(outcome: str, *, model: str | None, task: str | None, key: str) -> None:
        # Solo claves de la allowlist de app/services/tracing.py y solo el
        # hash: nunca prompts, nunca credenciales.
        try:
            from app.services import tracing as _tracing

            _tracing.trace_generation(
                name="llm.response_cache",
                model=model,
                metadata={
                    "task": task,
                    "route": model,
                    "status": outcome,
                    "prompt_hash": key.rsplit(":", 1)[-1],
                },
                usage={"cache_read": 1} if outcome == "hit" else None,
            )
        except Exception:  # noqa: BLE001 - tracing jamas rompe la llamada
            logger.debug("llm response cache trace failed", exc_info=True)

    # -- Redis ------------------------------------------------------------

    async def _redis(self):
        if self._client is not None:
            return self._client
        if self._client_failed:
            return None
        try:
            if self._redis_factory is not None:
                self._client = self._redis_factory()
            else:
                import redis.asyncio as redis_asyncio

                from app.core.redis_retry import no_retry_async

                self._client = redis_asyncio.from_url(
                    get_settings().redis_url,
                    socket_connect_timeout=self.connect_timeout,
                    socket_timeout=self.socket_timeout,
                    retry=no_retry_async(),
                )
        except Exception:  # noqa: BLE001 - fail-open: sin cache, no sin LLM
            self._client_failed = True
            self._count("error")
            logger.warning("llm response cache: cliente Redis no disponible", exc_info=True)
            return None
        return self._client

    async def get(
        self, key: str, *, model: str | None = None, task: str | None = None
    ) -> LLMResponse | None:
        client = await self._redis()
        if client is None:
            return None
        try:
            blob = await client.get(key)
        except Exception:  # noqa: BLE001 - fail-open
            self._count("error")
            logger.debug("llm response cache read failed", exc_info=True)
            return None
        if not blob:
            self._count("miss")
            self._trace("miss", model=model, task=task, key=key)
            return None
        try:
            response = decode_response(blob)
        except Exception:  # noqa: BLE001 - entrada corrupta = fallo, no un hit
            self._count("error")
            logger.warning("llm response cache: entrada ilegible; se descarta")
            await self._discard(client, key)
            return None
        if not is_cacheable(response):
            # Una entrada degradada que se colara en una version anterior no se
            # sirve: se borra y el caller va al proveedor.
            self._count("skip")
            await self._discard(client, key)
            return None
        self._count("hit")
        self._trace("hit", model=model, task=task, key=key)
        return as_cached(response, key)

    async def store(
        self,
        key: str,
        response: LLMResponse,
        *,
        used_fallback: bool = False,
        model: str | None = None,
        task: str | None = None,
    ) -> bool:
        if not is_cacheable(response, used_fallback=used_fallback):
            self.record_skip("degraded_or_truncated")
            return False
        client = await self._redis()
        if client is None:
            return False
        try:
            await client.eval(
                _STORE_SCRIPT,
                2,
                key,
                self._index_key,
                encode_response(response),
                self.ttl_seconds,
                self._next_score(),
                self.max_entries,
            )
        except Exception:  # noqa: BLE001 - fail-open
            self._count("error")
            logger.debug("llm response cache write failed", exc_info=True)
            return False
        self._count("write")
        self._trace("write", model=model, task=task, key=key)
        return True

    async def evict(self, key: str) -> None:
        """Retira una entrada que el llamador ha rechazado (fail-open)."""
        client = await self._redis()
        if client is None:
            return
        self._count("evict")
        await self._discard(client, key)

    async def _discard(self, client, key: str) -> None:
        try:
            await client.delete(key)
        except Exception:  # noqa: BLE001 - fail-open
            logger.debug("llm response cache delete failed", exc_info=True)

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if closer is None:
            return
        try:
            result = closer()
            if hasattr(result, "__await__"):
                await result
        except Exception:  # noqa: BLE001 - cerrando no se rompe nada
            logger.debug("llm response cache close failed", exc_info=True)


def _deployment_id(settings: Settings) -> str:
    # Namespace por despliegue: mismo host + mismo proveedor, misma cache;
    # cualquier otra combinacion, namespace distinto.
    return hashlib.sha256(
        f"{settings.opencode_go_base_url}|opencode-go".encode()
    ).hexdigest()[:8]


def _cache_namespace(settings: Settings) -> str:
    return f"{KEY_PREFIX}:{_deployment_id(settings)}"


def purge_llm_response_cache(
    settings: Settings | None = None,
    *,
    tenant_id: str | None = None,
    redis_factory=None,
) -> int:
    """Invalida la cache de respuestas LLM tras borrar una cuenta.

    La clave es un hash del sobre con el tenant dentro: el valor no guarda el
    tenant y dos tenants pueden compartir namespace. Por eso no se puede
    atribuir una entrada a un tenant sin cambiar el formato de clave. Un
    borrado de cuenta es infrecuente y la cache es solo aceleracion, asi que
    se invalida el namespace completo (nunca sirve datos de la cuenta borrada)
    en lugar de dejar residuo no atribuible.
    """
    resolved = settings or get_settings()
    config = load_cache_settings(resolved)
    if not config.enabled:
        return 0
    namespace = _cache_namespace(resolved)
    import redis as redis_sync

    from app.core.redis_retry import no_retry

    client = (
        redis_factory()
        if redis_factory is not None
        else redis_sync.from_url(
            resolved.redis_url,
            socket_connect_timeout=config.redis_connect_timeout,
            socket_timeout=config.redis_socket_timeout,
            retry=no_retry(),
        )
    )
    try:
        keys = list(client.scan_iter(match=f"{namespace}:e:*", count=500))
        deleted = int(client.delete(*keys)) if keys else 0
        client.delete(f"{namespace}:index")
        logger.info(
            "llm response cache purged tenant=%s entries=%s", tenant_id, deleted
        )
        return deleted
    finally:
        closer = getattr(client, "close", None)
        if closer is not None:
            try:
                closer()
            except Exception:  # noqa: BLE001 - cerrar nunca rompe el borrado
                logger.debug("llm response cache purge close failed", exc_info=True)


def build_response_cache(
    settings: Settings | None = None, *, redis_factory=None
) -> LLMResponseCache | None:
    """Cache construida desde la configuracion. None = cache desactivada."""
    resolved = settings or get_settings()
    config = load_cache_settings(resolved)
    if not config.enabled:
        return None
    deployment = _deployment_id(resolved)
    return LLMResponseCache(
        ttl_seconds=config.ttl_seconds,
        max_entries=config.max_entries,
        require_tenant=config.require_tenant,
        namespace=deployment,
        log_every=config.log_every,
        connect_timeout=config.redis_connect_timeout,
        socket_timeout=config.redis_socket_timeout,
        redis_factory=redis_factory,
    )