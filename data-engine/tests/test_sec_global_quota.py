"""Separate SEC clients/processes reserve one shared Redis quota and cooldown."""
import asyncio

import httpx
import pytest

from app.services.connectors import base, sec, sec_edgar, sec_pacing


class RedisQuota:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def eval(self, script, nkeys, *args):
        keys, vals = args[:nkeys], args[nkeys:]
        if nkeys == 2:
            now, interval, ttl = vals
            start = max(now, self.values.get(keys[0], 0), self.values.get(keys[1], 0))
            self.values[keys[0]] = start + interval
            return start - now
        until, ttl = vals
        self.values[keys[0]] = max(self.values.get(keys[0], 0), until)
        return self.values[keys[0]]


def test_two_processes_sync_async_share_slots():
    redis = RedisQuota()
    sleeps = []
    clock = lambda: 100.0

    async def sleep_async(delay):
        sleeps.append(delay)

    a = sec_pacing.SecPacer('sec', min_interval_seconds=0.1, redis_client_factory=lambda: redis,
                            wall_clock=clock, sleep=sleeps.append)
    b = sec_pacing.SecPacer('sec', min_interval_seconds=0.1, redis_client_factory=lambda: redis,
                            wall_clock=clock, sleep=sleeps.append)
    # Separate instances represent process-local memory; only Redis is shared.
    a.wait_sync()
    original = sec_pacing.asyncio.sleep
    sec_pacing.asyncio.sleep = sleep_async
    try:
        asyncio.run(b.wait())
        a.wait_sync()
    finally:
        sec_pacing.asyncio.sleep = original
    assert sleeps == [0.1, 0.2]


def test_long_retry_after_shared_without_sleep_or_http(monkeypatch):
    redis = RedisQuota()
    a = sec_pacing.SecPacer('sec', min_interval_seconds=0.1, redis_client_factory=lambda: redis)
    b = sec_pacing.SecPacer('sec', min_interval_seconds=0.1, redis_client_factory=lambda: redis)
    monkeypatch.setattr(sec_pacing, 'pacer', a)
    response = httpx.Response(429, headers={'Retry-After': '3600'}, request=httpx.Request('GET','https://www.sec.gov/x'))
    with pytest.raises(sec_pacing.SecQuotaDeferred) as raised:
        sec_pacing.rate_limited(response)
    assert raised.value.retry_after == 3600
    with pytest.raises(sec_pacing.SecQuotaDeferred):
        b.wait_sync()
    with pytest.raises(sec_pacing.SecQuotaDeferred):
        asyncio.run(b.wait())
    assert b.blocked_for_remote() > 3590


def test_all_connector_entrypoints_use_shared_quota(monkeypatch):
    class Probe:
        calls = []
        async def wait(self): self.calls.append('async')
        def wait_sync(self): self.calls.append('sync')
        def reset(self): pass
        def cool_down(self, seconds): self.calls.append(seconds)

    probe = Probe()
    monkeypatch.setattr(sec_pacing,'pacer',probe)
    base.reset_sec_rate_limiter()
    base.sec_throttle()
    asyncio.run(sec.SECClient()._throttle())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,json={},request=req))) as client:
            await sec_edgar._get_json('https://data.sec.gov/probe',client)
    asyncio.run(run())
    assert probe.calls == ['sync','async','async']


def test_worker_defers_accepted_work_with_full_window():
    import dramatiq

    from app.workers.dramatiq_app import _handle_actor_error

    with pytest.raises(dramatiq.Retry) as retry:
        _handle_actor_error('process_document', sec_pacing.SecQuotaDeferred(3600.1))
    assert retry.value.delay == 3600100


def test_cooldown_never_shortens_and_missing_header_gets_floor(monkeypatch):
    redis = RedisQuota()
    pacer = sec_pacing.SecPacer('sec', min_interval_seconds=0.1, redis_client_factory=lambda: redis)
    monkeypatch.setattr(sec_pacing, 'pacer', pacer)
    request = httpx.Request('GET', 'https://www.sec.gov/x')
    sec_pacing.rate_limited(httpx.Response(429, request=request))
    assert pacer.blocked_for_remote() > 59
    sec_pacing.rate_limited(httpx.Response(429, headers={'Retry-After': '1'}, request=request))
    assert pacer.blocked_for_remote() > 59


def test_non_rate_limit_does_not_open_cooldown(monkeypatch):
    class NoCooldown:
        def reset(self): pass
        def cool_down(self, seconds):
            pytest.fail('Only a 429 can open quota cooldown')
    monkeypatch.setattr(sec_pacing, 'pacer', NoCooldown())
    sec_pacing.rate_limited(httpx.Response(403, request=httpx.Request('GET', 'https://www.sec.gov/x')))


@pytest.mark.parametrize('header', ['inf', 'nan', '-5', 'nonsense'])
def test_bad_retry_after_has_safe_finite_floor(monkeypatch, header):
    waits = []
    class Probe:
        def reset(self): pass
        def cool_down(self, seconds): waits.append(seconds)
    monkeypatch.setattr(sec_pacing, 'pacer', Probe())
    sec_pacing.rate_limited(httpx.Response(429, headers={'Retry-After': header},
                           request=httpx.Request('GET','https://www.sec.gov/x')))
    assert waits == [60.0]
