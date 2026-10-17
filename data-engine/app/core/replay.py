"""Single-use nonce store for the signed identity bridge (anti-replay).

Every bound signature carries a random nonce that must be consumed exactly
once. Storage is Redis ``SET NX EX`` (atomic check-and-mark with TTL).

Availability posture: when Redis is unreachable the store may degrade to a
process-local TTL cache so a Redis outage does not become an auth outage —
but ONLY outside production (local/test). In production the store fails
closed with :class:`NonceBackendUnavailable` (HTTP 503 at the caller, like
the rate limiter), because the local cache only blocks replays seen by THIS
process and the single-use guarantee would silently weaken.
"""

from __future__ import annotations

import asyncio
import time

_local_nonces: dict[str, float] = {}
_local_lock = asyncio.Lock()


class NonceBackendUnavailable(RuntimeError):
    """Redis is down and production must not degrade to a local counter."""


async def consume_nonce(
    nonce_key: str,
    *,
    ttl_seconds: int,
    redis_url: str,
    use_redis: bool = True,
    allow_local_fallback: bool = True,
) -> bool:
    """Return True when ``nonce_key`` is fresh (first and only use).

    Returns False when the nonce was already consumed inside the TTL window.
    When Redis is unreachable and ``allow_local_fallback`` is False, raises
    :class:`NonceBackendUnavailable` instead of degrading to the local TTL
    cache. Production callers must pass ``allow_local_fallback=False``.
    """
    if use_redis:
        try:
            import redis.asyncio as redis

            from app.core.redis_retry import no_retry_async

            client = redis.from_url(redis_url, socket_connect_timeout=0.25, socket_timeout=0.5, retry=no_retry_async())
            try:
                acquired = await client.set(
                    nonce_key, "1", nx=True, ex=max(int(ttl_seconds), 1)
                )
            finally:
                await client.aclose()
            return bool(acquired)
        except Exception as exc:  # noqa: BLE001 — fail closed or local fallback
            if not allow_local_fallback:
                raise NonceBackendUnavailable(
                    "nonce store unreachable"
                ) from exc

    now = time.time()
    async with _local_lock:
        for key, expires in list(_local_nonces.items()):
            if expires <= now:
                _local_nonces.pop(key, None)
        if nonce_key in _local_nonces:
            return False
        _local_nonces[nonce_key] = now + max(int(ttl_seconds), 1)
        return True


def reset_local_nonces() -> None:
    """Test helper: clear the in-process nonce cache."""
    _local_nonces.clear()
