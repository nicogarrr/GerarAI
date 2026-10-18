import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import tracked_financial_refresh as svc


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def company(db, **kwargs):
    row = Company(ticker='KO', name='Coca-Cola', exchange='NYSE', currency='USD', company_type='operating', valuation_model='dcf', **kwargs)
    db.add(row)
    db.commit()
    return row


def seed(db, c):
    db.add(Document(company_id=c.id, title='SEC XBRL facts - KO', source_type='SEC', metadata_={'last_refreshed_at':'2026-10-18T10:00:00+00:00'}))
    db.add(FinancialFact(company_id=c.id, metric='revenue', period='2025:FY', value=Decimal('100'), unit='USD', source_type='SEC'))
    db.commit()


def test_recent_skips_without_network(db, monkeypatch):
    c=company(db); seed(db,c)
    async def forbidden(self, **kw): raise AssertionError('network')
    monkeypatch.setattr(svc.FinancialIngestionService,'refresh_from_sec',forbidden)
    result=asyncio.run(svc.refresh_free_financials(db,c,now=datetime(2026,10,18,12,tzinfo=UTC)))
    assert result['reason']=='actualizado_ultimas_24h'
    assert result['last_refreshed_at']=='2026-10-18T10:00:00+00:00'


def test_non_us_bare_ticker_is_not_resolved_as_us_namesake(db):
    c=company(db);c.exchange='BME';c.currency='EUR';db.commit()
    assert asyncio.run(svc.refresh_free_financials(db,c))['reason']=='emisor_no_sec'


def test_success_keeps_real_timestamp_and_zero_new_imports(db,monkeypatch):
    c=company(db)
    async def refresh(self, **kw): seed(db,c); return {'facts_imported':0}
    monkeypatch.setattr(svc.FinancialIngestionService,'refresh_from_sec',refresh)
    result=asyncio.run(svc.refresh_free_financials(db,c))
    assert result['status']=='ok' and result['facts_imported']==0
    assert result['last_refreshed_at']=='2026-10-18T10:00:00+00:00'


def test_failure_never_leaks_or_fabricates_refresh_date(db,monkeypatch):
    c=company(db)
    async def fail(self, **kw): raise RuntimeError('private-url')
    monkeypatch.setattr(svc.FinancialIngestionService,'refresh_from_sec',fail)
    result=asyncio.run(svc.refresh_free_financials(db,c))
    assert result['status']=='error' and result['last_refreshed_at'] is None
    assert 'private-url' not in str(result)


@pytest.mark.parametrize(('ticker', 'exchange'), [
    ('HD', 'NEW YORK STOCK EXCHANGE, INC.'),
    ('AMD', 'NASDAQ NMS - GLOBAL MARKET'),
])
def test_us_long_exchange_names_refresh_without_stored_cik(db, monkeypatch, ticker, exchange):
    c = company(db)
    c.ticker = ticker
    c.exchange = exchange
    c.cik = None
    db.commit()
    called = []
    async def refresh(self, **kwargs):
        called.append(kwargs['company'].ticker)
        db.add(FinancialFact(company_id=c.id, metric='revenue', period='2025:FY', value=Decimal('100'), unit='USD', source_type='SEC'))
        db.commit()
        return {'facts_imported': 1}
    monkeypatch.setattr(svc.FinancialIngestionService, 'refresh_from_sec', refresh)
    result = asyncio.run(svc.refresh_free_financials(db, c))
    assert called == [ticker]
    assert result['status'] == 'ok'
    assert result['facts_imported'] == 1


@pytest.mark.parametrize('exchange', ['BME', 'LONDON STOCK EXCHANGE', 'NOTNASDAQ', 'EURONEXT PARIS'])
def test_non_us_exchange_still_skipped_even_when_currency_usd(db, exchange):
    c = company(db)
    c.exchange = exchange
    db.commit()
    assert asyncio.run(svc.refresh_free_financials(db, c))['reason'] == 'emisor_no_sec'
