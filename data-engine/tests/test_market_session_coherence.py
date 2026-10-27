from datetime import UTC, date, datetime
from decimal import Decimal

import httpx

from app.api.routes import market
from app.models import Company
from app.services.propicks_price_service import PriceBar, _bar_is_final


def test_yahoo_ohlc_uses_same_closed_bar(monkeypatch):
    start, end = 1792393200, 1792423800
    payload = {'chart': {'result': [{'meta': {'currency': 'GBp', 'exchangeTimezoneName': 'Europe/London',
               'currentTradingPeriod': {'regular': {'start': start, 'end': end}}},
               'timestamp': [1792047600, 1792134000, start],
               'indicators': {'quote': [{'close': [4290, 4255, 4205], 'open': [4280, 4240, 4190],
                                        'high': [4300, 4270, 4220], 'low': [4270, 4230, 4180]}]}}]}}
    monkeypatch.setattr(market.time, 'time', lambda: 1792410000)
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))) as client:
        result = market._fetch_yahoo_quote(client, 'CGEO.L')
    assert result['c'] == 4255
    assert (result['o'], result['h'], result['l']) == (4240, 4270, 4230)
    assert result['ct'] == 1792134000


def test_london_closed_while_us_open_uses_source_session_end():
    company = Company(exchange='LSE', ticker='CGEO.L')
    end = datetime(2026, 10, 27, 16, 30, tzinfo=UTC)
    bar = PriceBar(date(2026, 10, 27), Decimal('43'), Decimal('43'), 1, 'GBP', 'Europe/London', end)
    assert not _bar_is_final(company, bar, datetime(2026, 10, 27, 16, 0, tzinfo=UTC))
    assert _bar_is_final(company, bar, datetime(2026, 10, 27, 17, 0, tzinfo=UTC))


def test_unknown_market_does_not_invent_current_session_close():
    company = Company(exchange='UNKNOWN', ticker='TEST.L')
    now = datetime(2026, 10, 27, 22, 0, tzinfo=UTC)
    assert not _bar_is_final(company, PriceBar(now.date(), Decimal(1), Decimal(1), 1), now)
    assert not _bar_is_final(company, PriceBar(date(2026, 10, 26), Decimal(1), Decimal(1), 1), now)
    assert _bar_is_final(company, PriceBar(date(2026, 10, 25), Decimal(1), Decimal(1), 1), now)


def test_timezone_without_matching_session_end_is_not_enough():
    company = Company(exchange='LSE', ticker='CGEO.L')
    now = datetime(2026, 10, 27, 22, 0, tzinfo=UTC)
    for end in (None, datetime(2026, 10, 26, 16, 30, tzinfo=UTC)):
        bar = PriceBar(now.date(), Decimal(1), Decimal(1), 1, 'GBP', 'Europe/London', end)
        assert not _bar_is_final(company, bar, now)


def test_sync_does_not_prefilter_london_by_new_york_clock():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base
    from app.services.market_close_sync import sync_official_closes

    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker='CGEO.L', name='Test', exchange='LSE', currency='GBP',
                          sector='S', industry='I', company_type='holding', valuation_model='unassigned',
                          special_sources=[], special_risks=[], factor_tags=[])
        db.add(company)
        db.flush()
        bar = PriceBar(date(2026, 10, 27), Decimal(43), Decimal(43), 1, 'GBP',
                       'Europe/London', datetime(2026, 10, 27, 16, 30, tzinfo=UTC))
        result = sync_official_closes(db, now=datetime(2026, 10, 27, 17, 0, tzinfo=UTC),
                                     fetcher=lambda symbols, period: {'CGEO.L': [bar]})
        assert result['bars_written'] == 1
        assert result['partial_session_skipped'] is False
