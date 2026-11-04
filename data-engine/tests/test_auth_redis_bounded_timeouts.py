"""Security Redis tolerates short cold-start stalls without retrying writes."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core import rate_limit, replay


def test_security_clients_have_bounded_timeouts_and_no_hidden_retry(monkeypatch):
    async def scenario():
        import redis.asyncio

        seen = []
        client = AsyncMock()
        client.set.return_value = True
        client.zcount.return_value = 1
        pipe = AsyncMock()
        pipe.execute.return_value = [0, 1, 1, True, []]
        pipe.zremrangebyscore = lambda *a: None
        pipe.zadd = lambda *a: None
        pipe.zcard = lambda *a: None
        pipe.expire = lambda *a: None
        pipe.zrange = lambda *a, **kw: None
        pipe.__aenter__.return_value = pipe
        from unittest.mock import Mock
        client.pipeline = Mock(return_value=pipe)

        def factory(redis_url, **kwargs):
            seen.append(kwargs)
            return client

        monkeypatch.setattr(rate_limit, '_now', lambda: 100.0)
        monkeypatch.setattr(redis.asyncio, 'from_url', factory)
        assert await replay.consume_nonce('nonce', ttl_seconds=60, redis_url='redis://unused', allow_local_fallback=False)
        assert await rate_limit._record_hit('rate', window_seconds=60, use_redis=True, redis_url='redis://unused', degrade_to_local=False) == (1, 60)
        assert await rate_limit._count_hits('rate', use_redis=True, redis_url='redis://unused') == 1
        assert len(seen) == 3
        for kwargs in seen:
            assert kwargs['socket_connect_timeout'] == 1.0
            assert kwargs['socket_timeout'] == 1.5
            assert kwargs['retry']._retries == 0

    asyncio.run(scenario())

def test_ambiguous_nonce_write_times_out_once_and_stays_fail_closed(monkeypatch):
    async def scenario():
        import redis.asyncio

        client = AsyncMock()
        client.set.side_effect = TimeoutError('reply lost after SET NX')
        monkeypatch.setattr(redis.asyncio, 'from_url', lambda *a, **kw: client)
        with pytest.raises(replay.NonceBackendUnavailable):
            await replay.consume_nonce('nonce', ttl_seconds=60, redis_url='redis://unused', allow_local_fallback=False)
        client.set.assert_awaited_once_with('nonce', '1', nx=True, ex=60)
        client.aclose.assert_awaited_once()

    asyncio.run(scenario())

def test_ambiguous_counter_transaction_is_not_retried(monkeypatch):
    async def scenario():
        from unittest.mock import Mock

        import redis.asyncio

        client = AsyncMock()
        pipe = AsyncMock()
        pipe.__aenter__.return_value = pipe
        for name in ('zremrangebyscore', 'zadd', 'zcard', 'expire', 'zrange'):
            setattr(pipe, name, Mock())
        pipe.execute.side_effect = TimeoutError('EXEC response lost')
        client.pipeline = Mock(return_value=pipe)
        monkeypatch.setattr(redis.asyncio, 'from_url', lambda *a, **kw: client)
        with pytest.raises(rate_limit.RateLimitBackendUnavailable):
            await rate_limit._record_hit('rate', window_seconds=60, use_redis=True,
                                         redis_url='redis://unused', degrade_to_local=False)
        pipe.execute.assert_awaited_once()
        client.aclose.assert_awaited_once()

    asyncio.run(scenario())

