"""Cached Yahoo key figures retain their actual fetch time."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services import key_stats_service as svc


@pytest.fixture
def setup(monkeypatch):
    clock = {"now": 1_800_000_000.0}
    monkeypatch.setattr(svc.time, "time", lambda: clock["now"])
    monkeypatch.setattr(svc, "_own_data", lambda *args: {"found": True, "yahoo": "EXAMPLE", "currency": "USD"})
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return {"beta": 1.25, "currency": "USD", "fiftyTwoWeekLow": 10, "fiftyTwoWeekHigh": 20}

    monkeypatch.setattr(svc, "_fetch_yahoo_info", fetch)
    return clock, calls, svc.KeyStatsService()


def test_cached_beta_and_range_do_not_get_a_new_fetch_timestamp(setup):
    clock, calls, service = setup
    first = asyncio.run(service.get(None, "EXAMPLE"))
    clock["now"] += 3600
    second = asyncio.run(service.get(None, "EXAMPLE"))
    assert calls == ["EXAMPLE"]
    assert first.beta == second.beta
    assert first.range_52w == second.range_52w
    assert first.fetched_at == second.fetched_at


def test_expired_cache_gets_a_new_source_read(setup):
    clock, calls, service = setup
    first = asyncio.run(service.get(None, "EXAMPLE"))
    clock["now"] += svc.CACHE_TTL_SECONDS
    second = asyncio.run(service.get(None, "EXAMPLE"))
    assert calls == ["EXAMPLE", "EXAMPLE"]
    assert second.fetched_at == int(clock["now"])
    assert second.fetched_at != first.fetched_at


def test_yahoo_failure_still_has_no_stale_fallback(setup, monkeypatch):
    clock, calls, service = setup
    asyncio.run(service.get(None, "EXAMPLE"))
    clock["now"] += svc.CACHE_TTL_SECONDS
    monkeypatch.setattr(service, "_yahoo", AsyncMock(return_value=None))
    result = asyncio.run(service.get(None, "EXAMPLE"))
    assert result.beta is None and result.range_52w is None
    assert result.note
    assert result.fetched_at == int(clock["now"])


def test_real_yahoo_failure_path_and_own_db_failure_stay_honest(setup, monkeypatch):
    clock, calls, service = setup

    def fail(*args):
        raise RuntimeError('source unavailable')

    monkeypatch.setattr(svc, '_own_data', fail)
    monkeypatch.setattr(svc, '_fetch_yahoo_info', fail)
    result = asyncio.run(service.get(None, 'EXAMPLE'))
    assert result.fetched_at == int(clock['now'])
    assert result.note and result.beta is None
    assert not service._cache


def test_successful_dates_and_currency_keep_cached_read_time(setup, monkeypatch):
    clock, calls, service = setup
    today = svc.datetime.now(svc.UTC).date()
    timestamp = int(svc.datetime.combine(today, svc.datetime.min.time(), tzinfo=svc.UTC).timestamp())
    monkeypatch.setattr(svc, '_own_data', lambda *args: {'found': False, 'yahoo': 'EXAMPLE', 'currency': None})
    monkeypatch.setattr(svc, '_fetch_yahoo_info', lambda *args: {
        'beta': 0.8, 'currency': 'USD', 'exDividendDate': timestamp,
        'earningsTimestamp': timestamp, 'isEarningsDateEstimate': True,
    })
    first = asyncio.run(service.get(None, 'EXAMPLE'))
    clock['now'] += 60
    second = asyncio.run(service.get(None, 'EXAMPLE'))
    assert second.fetched_at == first.fetched_at
    assert second.currency == 'USD'
    assert second.next_earnings.date == today.isoformat()
    assert second.ex_dividend.date == today.isoformat()
