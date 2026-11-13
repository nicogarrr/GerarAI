"""The UI's catalysts endpoint must carry NASDAQ stale-day notices."""
import asyncio
from datetime import date

import pytest

from app.api.routes import calendar as routes


@pytest.mark.parametrize('held', [True, False])
@pytest.mark.parametrize('stale', [True, False])
def test_catalysts_returns_union_of_stale_source_days(monkeypatch, held, stale):
    monkeypatch.setattr(routes.catalyst_service, 'held_tickers', lambda _: ({'ABC'}, {'ABC'}) if held else (set(), set()))
    monkeypatch.setattr(routes.catalyst_service, 'watchlist_us_tickers', lambda *_: set())
    monkeypatch.setattr(routes.catalyst_service, 'watchlist_tickers', lambda *_: set())
    monkeypatch.setattr(routes.catalyst_service, 'pending_actions', lambda *_: [])
    monkeypatch.setattr(routes.catalyst_service, 'upcoming_dividend_records', lambda *_: [])
    monkeypatch.setattr(routes.catalyst_service, 'build_catalysts', lambda **_: [])
    async def earnings(*_):
        return {'status': 'partial' if stale else 'ok', 'events': [], 'errors': [],
                'stale_days': ['2026-11-14', '2026-11-13'] if stale else []}
    async def dividends(*_):
        return {'status': 'partial' if stale else 'ok', 'events': [], 'errors': [],
                'stale_days': ['2026-11-14', '2026-11-15'] if stale else []}
    async def filings(*_, **kwargs):
        return {'status': 'ok', 'events': [], 'errors': []}
    monkeypatch.setattr(routes.calendar_connector, 'fetch_earnings_range', earnings)
    monkeypatch.setattr(routes.calendar_connector, 'fetch_dividends_range', dividends)
    monkeypatch.setattr(routes.catalyst_service, 'fetch_filing_deadlines', filings)
    result = asyncio.run(routes.catalysts_calendar(date(2026, 11, 13), date(2026, 11, 16), object()))
    assert result['stale_days'] == (['2026-11-13', '2026-11-14', '2026-11-15'] if held and stale else [])
