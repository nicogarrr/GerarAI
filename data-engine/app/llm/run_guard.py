"""Tope DURO por corrida para las llamadas HTTP a un proveedor LLM.

Contrato:

- Inactivo por defecto: sin guard en el contexto el adaptador se comporta
  exactamente igual que antes (no hay cambio de comportamiento al desplegar).
- Activo (``activate(guard)``): TODA peticion HTTP que sale del adaptador
  (cada intento, reintento y respaldo pasa por ``LLMProvider._send``) reserva
  cupo ANTES de tocar la red. Si el cupo no cabe, se lanza
  ``LLMGuardAbort`` y no se envia nada.
- El contador vive FUERA del proceso (Redis, atomico) y se identifica por
  ``run_id``: no se reinicia por instancia de proveedor, por intento del job
  ni por reentrega a otro worker. Si el almacen falla, el guard CIERRA
  (no deja pasar la llamada).
- Limites: destino (host https permitido), modelo permitido, numero de POST,
  ``max_tokens`` solicitado por peticion y suma de ``max_tokens`` solicitados
  (peor caso de salida facturable). El cupo se reserva por lo SOLICITADO, no
  por lo consumido: contar despues no es un tope.

Modo estricto (deadline_ts, durable en el job): el deadline absoluto se
comprueba antes de cada reserva; un contador ausente tras la inicializacion
(expirado o desalojado) aborta en vez de recrearse. Sin deadline: legado.

Vida del contador (legado): el TTL se fija UNA vez (en la primera reserva del run_id) y
NO se renueva. Pasado el TTL (7 dias por defecto) el contador de ese run_id
desaparece y el cupo vuelve a empezar: el tope es por ciclo de vida de la
corrida, no perpetuo. Un run_id nuevo tiene cupo nuevo por construccion.

Limites del diseno (no son garantias): no cuenta tokens de entrada, no
conoce el precio real y no impide llamadas por rutas que no pasen por
``LLMProvider._send``.
"""

from __future__ import annotations

import contextlib
import contextvars
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from app.llm.errors import LLMError


class LLMGuardAbort(LLMError):
    """La llamada se aborta ANTES de la red. ``reason`` es una categoria fija."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"llm_guard_abort:{reason}")


@dataclass(frozen=True)
class LLMRunGuard:
    run_id: str
    allowed_hosts: frozenset[str]
    allowed_models: frozenset[str]
    max_posts: int
    max_tokens_per_request: int
    max_total_output_tokens: int
    store: CounterStore
    #: Epoch s absoluto (durable, viene del job en BD). Con deadline el modo es
    #: ESTRICTO: se comprueba antes de CADA reserva; un contador ausente
    #: (expirado o desalojado) NO se recrea: aborta. Sin deadline = legado.
    deadline_ts: float | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id is required")
        if not self.allowed_hosts or not self.allowed_models:
            raise ValueError("allowed_hosts and allowed_models are required")
        if min(self.max_posts, self.max_tokens_per_request, self.max_total_output_tokens) <= 0:
            raise ValueError("limits must be positive")


class CounterStore(Protocol):
    def reserve(
        self, run_id: str, *, posts: int, tokens: int, max_posts: int, max_tokens: int,
        deadline_ts: float | None = None,
    ) -> bool: ...

    def init(self, run_id: str, *, deadline_ts: float) -> None: ...


class InMemoryCounterStore:
    """Solo para tests y procesos unicos: NO cruza procesos."""

    def __init__(self) -> None:
        self.state: dict[str, tuple[int, int]] = {}

    def init(self, run_id: str, *, deadline_ts: float) -> None:
        self.state.setdefault(run_id, (0, 0))

    def reserve(
        self, run_id: str, *, posts: int, tokens: int, max_posts: int, max_tokens: int,
        deadline_ts: float | None = None,
    ) -> bool:
        if deadline_ts is not None:
            if time.time() >= deadline_ts:
                raise LLMGuardAbort("run_deadline_exceeded")
            if run_id not in self.state:
                raise LLMGuardAbort("counter_missing")
        used_posts, used_tokens = self.state.get(run_id, (0, 0))
        if used_posts + posts > max_posts or used_tokens + tokens > max_tokens:
            return False
        self.state[run_id] = (used_posts + posts, used_tokens + tokens)
        return True


_RESERVE_LUA = """
local dl = tonumber(ARGV[6] or '0')
if dl > 0 then
  local now = redis.call('TIME')
  if tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000) >= dl then
    return -2
  end
  if redis.call('EXISTS', KEYS[1]) == 0 then
    return -1
  end
end
local p = tonumber(redis.call('HGET', KEYS[1], 'posts') or '0')
local t = tonumber(redis.call('HGET', KEYS[1], 'tokens') or '0')
if p + tonumber(ARGV[1]) > tonumber(ARGV[3]) or t + tonumber(ARGV[2]) > tonumber(ARGV[4]) then
  return 0
end
redis.call('HINCRBY', KEYS[1], 'posts', ARGV[1])
redis.call('HINCRBY', KEYS[1], 'tokens', ARGV[2])
if dl == 0 and redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
end
return 1
"""

# Crea el contador SOLO si no existe (nunca resetea uno vivo); expira en el
# deadline absoluto, no en un TTL relativo renovable.
_INIT_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  redis.call('HSET', KEYS[1], 'posts', 0, 'tokens', 0)
  redis.call('PEXPIREAT', KEYS[1], tonumber(ARGV[1]))
end
return 1
"""


class RedisCounterStore:
    """Contador atomico (script Lua) compartido por todos los procesos."""

    def __init__(self, client: Any, *, ttl_seconds: int = 7 * 24 * 3600, prefix: str = "llmguard:") -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._prefix = prefix

    def init(self, run_id: str, *, deadline_ts: float) -> None:
        try:
            self._client.eval(_INIT_LUA, 1, self._prefix + run_id, int(deadline_ts * 1000))
        except Exception:
            raise LLMGuardAbort("store_unavailable") from None

    def reserve(
        self, run_id: str, *, posts: int, tokens: int, max_posts: int, max_tokens: int,
        deadline_ts: float | None = None,
    ) -> bool:
        args = [posts, tokens, max_posts, max_tokens, self._ttl]
        if deadline_ts is not None:
            args.append(int(deadline_ts * 1000))
        try:
            ok = int(self._client.eval(_RESERVE_LUA, 1, self._prefix + run_id, *args))
        except Exception:
            raise LLMGuardAbort("store_unavailable") from None
        if ok == -2:
            raise LLMGuardAbort("run_deadline_exceeded")
        if ok == -1:
            raise LLMGuardAbort("counter_missing")
        return ok == 1


_current: contextvars.ContextVar[LLMRunGuard | None] = contextvars.ContextVar("llm_run_guard", default=None)


def current_guard() -> LLMRunGuard | None:
    return _current.get()


@contextlib.contextmanager
def activate(guard: LLMRunGuard) -> Iterator[LLMRunGuard]:
    token = _current.set(guard)
    try:
        yield guard
    finally:
        _current.reset(token)


def _reserve(guard: LLMRunGuard, *, tokens: int) -> None:
    """Unica via de reserva: deadline comprobado antes de CADA POST (python) y
    otra vez dentro del script atomico (reloj de Redis)."""
    if guard.deadline_ts is not None and time.time() >= guard.deadline_ts:
        raise LLMGuardAbort("run_deadline_exceeded")
    if not guard.store.reserve(
        guard.run_id,
        posts=1,
        tokens=tokens,
        max_posts=guard.max_posts,
        max_tokens=guard.max_total_output_tokens,
        deadline_ts=guard.deadline_ts,
    ):
        raise LLMGuardAbort("run_budget_exhausted")


def reserve_request(url: str, payload: Any, *, guard_required: bool = False) -> None:
    """Llamada previa a cada POST. No hace nada si no hay guard y no es obligatorio."""
    guard = _current.get()
    if guard is None:
        if guard_required:
            raise LLMGuardAbort("guard_required_but_inactive")
        return
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or (parsed.hostname or "") not in guard.allowed_hosts:
        raise LLMGuardAbort("destination_not_allowed")
    model = payload.get("model") if hasattr(payload, "get") else None
    if model not in guard.allowed_models:
        raise LLMGuardAbort("model_not_allowed")
    requested = payload.get("max_tokens")
    if not isinstance(requested, int) or isinstance(requested, bool) or requested <= 0:
        raise LLMGuardAbort("max_tokens_missing")
    if requested > guard.max_tokens_per_request:
        raise LLMGuardAbort("max_tokens_per_request_exceeded")
    _reserve(guard, tokens=requested)


def reserve_post_without_tokens(url: str, *, guard_required: bool = False) -> None:
    """Para clientes que no envian ``max_tokens`` (p.ej. Jev): con guard activo
    el destino debe estar permitido y CADA POST (reintentos incluidos) reserva
    1 POST contra el tope de la corrida antes de la red. Tokens de salida: 0
    (la API no soporta max_tokens; no se inventa un coste total)."""
    guard = _current.get()
    if guard is None:
        if guard_required:
            raise LLMGuardAbort("guard_required_but_inactive")
        return
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or (parsed.hostname or "") not in guard.allowed_hosts:
        raise LLMGuardAbort("destination_not_allowed")
    _reserve(guard, tokens=0)
