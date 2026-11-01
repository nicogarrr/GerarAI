"""One SEC egress quota per IP across sync/async connectors and processes."""
import asyncio
import math
from functools import lru_cache

from app.services.connectors.global_pacing import _CLAIM_SLOT_LUA, GlobalPacer


def _redis():
    from app.core.config import get_settings

    url = get_settings().redis_url
    if not url:
        return None
    return _client_for_url(url)


@lru_cache(maxsize=4)
def _client_for_url(url):
    from redis import Redis

    from app.core.redis_retry import no_retry

    return Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=1.0, retry=no_retry())


class SecQuotaDeferred(RuntimeError):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"SEC 429: shared cooldown, retry after {retry_after:.1f}s")
        self.retry_after = retry_after


class SecPacer(GlobalPacer):
    def _check_long_cooldown(self) -> None:
        remaining = self.blocked_for()
        if remaining > 60:
            raise SecQuotaDeferred(remaining)

    def wait_sync(self) -> None:
        self._check_long_cooldown()
        super().wait_sync()

    async def wait(self) -> None:
        self._check_long_cooldown()
        client = self._client()
        if client is not None:
            try:
                wait_ms = client.eval(
                    _CLAIM_SLOT_LUA, 2, self._slot_key, self._cooldown_key,
                    int(self._wall() * 1000), int(self.min_interval_seconds * 1000), self._slot_ttl_ms,
                )
            except Exception:  # noqa: BLE001 - Redis unavailable: shared local fallback
                pass
            else:
                if float(wait_ms) > 0:
                    await asyncio.sleep(float(wait_ms) / 1000.0)
                return
        # Local fallback shares its reservation with synchronous consumers,
        # but must never block the event loop with time.sleep.
        with self._local_lock:
            now = self._monotonic()
            start = max(now, self._local_next, self._local_blocked_until)
            self._local_next = start + self.min_interval_seconds
        if start > now:
            await asyncio.sleep(start - now)


# 150 ms reserves headroom below the 10/s ceiling under VM scheduling jitter.
pacer = SecPacer("sec", min_interval_seconds=0.15, redis_client_factory=_redis)


def rate_limited(response, *, inline_cap: float = 60.0) -> None:
    """Publish the entire Retry-After, including final attempts. Never retry early."""
    from app.services.connectors.base import retry_after_seconds

    if getattr(response, "status_code", None) != 429:
        return
    window = retry_after_seconds(response, cap=float("inf")) or 60.0
    if not math.isfinite(window) or window <= 0:
        window = 60.0
    pacer.cool_down(window)
    if window > inline_cap:
        raise SecQuotaDeferred(window)
