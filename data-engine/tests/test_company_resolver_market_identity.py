"""A venue suffix must not silently select a base ticker on another market."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.company_resolver import resolve_companies, resolve_company


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def company(db, ticker, exchange, currency):
    row = Company(ticker=ticker, name=ticker, exchange=exchange, currency=currency,
                  company_type='standard', valuation_model='standard_dcf')
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize('requested,venue,currency', [
    ('ERF.PA', 'NYSE', 'USD'),
    ('ALX.TO', 'NASDAQ', 'USD'),
    ('GCC.MX', 'LONDON STOCK EXCHANGE', 'GBP'),
    ('ABC.L', 'TORONTO STOCK EXCHANGE', 'CAD'),
    ('ABC.AS', 'EURONEXT PARIS', 'EUR'),
])
def test_foreign_suffix_rejects_other_known_market(db, requested, venue, currency):
    company(db, requested.rsplit('.', 1)[0], venue, currency)
    assert resolve_company(db, requested) is None
    assert resolve_companies(db, [requested]) == ([], [requested])


@pytest.mark.parametrize('requested,venue,currency', [
    ('ABC.TO', 'TORONTO STOCK EXCHANGE', 'CAD'),
    ('ABC.PA', 'EURONEXT PARIS', 'EUR'),
    ('ABC.L', 'LONDON STOCK EXCHANGE', 'USD'),
    ('ABC.AS', 'EURONEXT AMSTERDAM', 'EUR'),
])
def test_same_market_legacy_base_still_resolves(db, requested, venue, currency):
    row = company(db, 'ABC', venue, currency)
    assert resolve_company(db, requested) is row
    assert resolve_companies(db, [requested]) == ([row], [])


def test_exact_listing_and_base_remain_distinct(db):
    us = company(db, 'ABC', 'NASDAQ', 'USD')
    ca = company(db, 'ABC.TO', 'TORONTO STOCK EXCHANGE', 'CAD')
    assert resolve_company(db, 'ABC.TO') is ca
    assert resolve_companies(db, ['ABC.TO', 'ABC']) == ([ca, us], [])


@pytest.mark.parametrize('stored,requested', [('BRK-B', 'BRK.B'), ('BRK.B', 'BRK-B')])
def test_real_us_share_class_not_mistaken_for_market(db, stored, requested):
    row = company(db, stored, 'NYSE', 'USD')
    assert resolve_company(db, requested) is row
    assert resolve_companies(db, [requested]) == ([row], [])
