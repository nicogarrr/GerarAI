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

Limites del diseno (no son garantias): no cuenta tokens de entrada, no
conoce el precio real y no impide llamadas por rutas que no pasen por
``LLMProvider._send``.
"""

from __future__ import annotations

import contextlib
import contextvars
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

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id is required")
        if not self.allowed_hosts or not self.allowed_models:
            raise ValueError("allowed_hosts and allowed_models are required")
        if min(self.max_posts, self.max_tokens_per_request, self.max_total_output_tokens) <= 0:
            raise ValueError("limits must be positive")


class CounterStore(Protocol):
    def reserve(
        self, run_id: str, *, posts: int, tokens: int, max_posts: int, max_tokens: int
    ) -> bool:
        """Reserva ATOMICAMENTE; devuelve False (sin cambiar nada) si no cabe."""


class InMemoryCounterStore:
    """Solo para tests y procesos unicos: NO cruza procesos."""

    def __init__(self) -> None:
        self.state: dict[str, tuple[int, int]] = {}

    def reserve(self, run_id: str, *, posts: int, tokens: int, max_posts: int, max_tokens: int) -> bool:
        used_posts, used_tokens = self.state.get(run_id, (0, 0))
        if used_posts + posts > max_posts or used_tokens + tokens > max_tokens:
            return False
        self.state[run_id] = (used_posts + posts, used_tokens + tokens)
        return True


_RESERVE_LUA = """
local p = tonumber(redis.call('HGET', KEYS[1], 'posts') or '0')
local t = tonumber(redis.call('HGET', KEYS[1], 'tokens') or '0')
if p + tonumber(ARGV[1]) > tonumber(ARGV[3]) or t + tonumber(ARGV[2]) > tonumber(ARGV[4]) then
  return 0
end
redis.call('HINCRBY', KEYS[1], 'posts', ARGV[1])
redis.call('HINCRBY', KEYS[1], 'tokens', ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return 1
"""


class RedisCounterStore:
    """Contador atomico (script Lua) compartido por todos los procesos."""

    def __init__(self, client: Any, *, ttl_seconds: int = 7 * 24 * 3600, prefix: str = "llmguard:") -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._prefix = prefix

    def reserve(self, run_id: str, *, posts: int, tokens: int, max_posts: int, max_tokens: int) -> bool:
        try:
            ok = self._client.eval(
                _RESERVE_LUA, 1, self._prefix + run_id, posts, tokens, max_posts, max_tokens, self._ttl
            )
        except Exception:
            raise LLMGuardAbort("store_unavailable") from None
        return int(ok) == 1


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
    if not guard.store.reserve(
        guard.run_id,
        posts=1,
        tokens=requested,
        max_posts=guard.max_posts,
        max_tokens=guard.max_total_output_tokens,
    ):
        raise LLMGuardAbort("run_budget_exhausted")
