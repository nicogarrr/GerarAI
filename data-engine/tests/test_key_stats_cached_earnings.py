"""A six-hour Yahoo cache must not call yesterday's event upcoming."""
import asyncio
from datetime import UTC, datetime, timedelta

from app.services import key_stats_service as svc


def test_cached_earnings_are_rechecked_when_the_utc_day_changes(monkeypatch):
    clock = {'now': datetime(2026, 11, 12, 23, 30, tzinfo=UTC)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock['now']

    monkeypatch.setattr(svc, 'datetime', Clock)
    monkeypatch.setattr(svc.time, 'time', lambda: clock['now'].timestamp())
    monkeypatch.setattr(svc, '_own_data', lambda *args: {'yahoo': 'EXAMPLE', 'currency': 'USD'})
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return {'earningsTimestamp': int(clock['now'].timestamp()),
                'isEarningsDateEstimate': True, 'beta': 1.25, 'currency': 'USD'}

    monkeypatch.setattr(svc, '_fetch_yahoo_info', fetch)
    service = svc.KeyStatsService()
    first = asyncio.run(service.get(None, 'EXAMPLE'))
    assert first.next_earnings.date == '2026-11-12'
    clock['now'] += timedelta(hours=1)
    second = asyncio.run(service.get(None, 'EXAMPLE'))
    assert calls == ['EXAMPLE'], 'reuse the valid six-hour source cache'
    assert second.next_earnings is None, 'yesterday is no longer upcoming'
    assert second.beta.value == 1.25
