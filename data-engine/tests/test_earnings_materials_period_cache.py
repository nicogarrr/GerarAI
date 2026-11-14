"""The same event date can carry a corrected closed quarter in the calendar."""
import asyncio
import json
import time
from datetime import date

import pytest

from app.services import earnings_materials_service as service
from tests.test_earnings_materials_redis import BoomSEC, FakeRedis
from tests.test_earnings_materials_service import INDEX, TSLA, FakeSEC


@pytest.mark.parametrize('layer', ['memory', 'redis'])
def test_cached_links_still_require_the_current_fiscal_period(monkeypatch, layer):
    monkeypatch.setattr(service, '_cache', {})
    redis = FakeRedis()
    monkeypatch.setattr(service, '_materials_redis', lambda: redis if layer == 'redis' else None)
    sec = FakeSEC(TSLA, {
        '0001628280-26-049213-index.htm': INDEX,
        'exhibit991.htm': '<h1>Second quarter 2026 results</h1>Revenue for the quarter ended June 30, 2026.',
        'deck.htm': 'No period identity',
    })
    event = {'ticker': 'TSLA', 'date': '2026-07-22', 'fiscal_label': 'Jun/2026', 'confirmed': True}
    key = 'TSLA|2026-07-22'
    first = asyncio.run(service.materials_for_events([event], date(2026, 7, 24), sec=sec))
    assert first[key]['status'] == 'ok'
    if layer == 'redis':
        service.reset_cache()
    event['fiscal_label'] = 'Mar/2026'
    second = asyncio.run(service.materials_for_events([event], date(2026, 7, 24), sec=sec))
    assert second[key]['status'] == 'periodo_no_coincide'
    assert second[key]['documents'] == []


@pytest.mark.parametrize('layer', ['memory', 'redis'])
def test_period_cache_identity_is_normalized_and_public_key_unchanged(monkeypatch, layer):
    monkeypatch.setattr(service, '_cache', {})
    event = {'ticker': 'TSLA', 'date': '2026-07-22', 'fiscal_label': 'Jun/2026', 'confirmed': True}
    identity = service._materials_cache_key(event)
    value = service._result('ok')
    redis = FakeRedis({service._materials_redis_key(identity): json.dumps(value)})
    monkeypatch.setattr(service, '_materials_redis', lambda: redis)
    if layer == 'memory':
        service._cache[identity] = (time.monotonic(), value)
    event['fiscal_label'] = ' JUN/2026 '
    result = asyncio.run(service.materials_for_events([event], date(2026, 7, 24), sec=BoomSEC()))
    assert result == {'TSLA|2026-07-22': value}


def test_legacy_redis_result_without_period_context_is_not_reused(monkeypatch):
    monkeypatch.setattr(service, '_cache', {})
    redis = FakeRedis({'cavaai:earnings-materials:TSLA|2026-07-22': json.dumps(service._result('ok'))})
    monkeypatch.setattr(service, '_materials_redis', lambda: redis)
    class MissingSEC:
        async def cik_for_ticker(self, ticker):
            return None
    event = {'ticker': 'TSLA', 'date': '2026-07-22', 'fiscal_label': 'Mar/2026', 'confirmed': True}
    result = asyncio.run(service.materials_for_events([event], date(2026, 7, 24), sec=MissingSEC()))
    assert result['TSLA|2026-07-22']['status'] == 'sin_cobertura_sec'
    assert redis.set_calls[0][0].startswith('cavaai:earnings-materials:v2:')
