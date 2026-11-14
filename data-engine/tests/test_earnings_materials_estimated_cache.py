"""A cached official link cannot confirm an event now marked estimated."""
import asyncio
import json
import time
from datetime import date

import pytest

from app.services import earnings_materials_service as service
from tests.test_earnings_materials_redis import OK_VALUE, BoomSEC, FakeRedis


@pytest.mark.parametrize('layer', ['memory', 'redis'])
def test_estimated_event_does_not_reuse_confirmed_materials(monkeypatch, layer):
    monkeypatch.setattr(service, '_cache', {})
    key = 'TSLA|2026-07-22'
    cache_key = service._materials_cache_key({'ticker': 'TSLA', 'date': '2026-07-22', 'fiscal_label': 'Jun/2026'})
    redis = FakeRedis({service._materials_redis_key(cache_key): json.dumps(OK_VALUE)})
    monkeypatch.setattr(service, '_materials_redis', lambda: redis)
    if layer == 'memory':
        service._cache[cache_key] = (time.monotonic(), OK_VALUE)
    events = [{'ticker': 'TSLA', 'date': '2026-07-22', 'fiscal_label': 'Jun/2026', 'confirmed': False}]
    out = asyncio.run(service.materials_for_events(events, date(2026, 7, 24), sec=BoomSEC()))
    assert out[key] == {'status': 'sin_cobertura_sec', 'filed_at': None, 'filing_url': None, 'documents': []}
    assert redis.set_calls == []
