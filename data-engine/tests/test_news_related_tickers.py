"""Tickers relacionados de una noticia: evidencia explicita y cierres datados."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice
from app.services import news_related_tickers as nrt
from app.services.news_related_tickers import (
    build_index,
    mentioned_companies,
    related_for_events,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    nrt._INDEX_CACHE.update(at=0.0, value=None)
    yield
    nrt._INDEX_CACHE.update(at=0.0, value=None)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _co(db, ticker, name, currency="USD", exchange="NASDAQ"):
    company = Company(
        ticker=ticker, name=name, exchange=exchange, currency=currency,
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _px(db, company, day, close):
    db.add(MarketPrice(company_id=company.id, date=day, close=close, source="yfinance"))


TEXT = (
    "AST SpaceMobile letter of intent with Deutsche Telekom, Orange, Telefonica "
    "and Vodafone Group (NASDAQ: VOD) to explore a joint bid"
)


def test_mentions_use_full_names_and_exchange_tags_only(db):
    asts = _co(db, "ASTS", "AST SpaceMobile, Inc.")
    dt = _co(db, "DTE", "Deutsche Telekom AG", exchange="XETRA")
    orange = _co(db, "ORAN", "Orange SA", exchange="EPA")
    tef = _co(db, "TEF", "Telefónica, S.A.", exchange="BME")
    vod = _co(db, "VOD", "Vodafone Group Plc")
    by_name, by_ticker = build_index([asts, dt, orange, tef, vod])
    found = {c.ticker for c in mentioned_companies(TEXT, by_name, by_ticker)}
    assert found == {"ASTS", "DTE", "TEF", "VOD"}  # «Orange» es palabra corriente: no se vincula
    assert mentioned_companies("Alert on VOD and DTE shares", by_name, by_ticker) == []  # sigla suelta: no
    assert {c.ticker for c in mentioned_companies("Watch $DTE today", by_name, by_ticker)} == {"DTE"}


def test_ambiguous_name_is_dropped(db):
    a = _co(db, "AAA", "Northern Star Resources Ltd")
    b = _co(db, "BBB", "Northern Star Resources Inc")
    by_name, by_ticker = build_index([a, b])
    assert mentioned_companies("Northern Star Resources reports", by_name, by_ticker) == []


def test_related_has_dated_close_and_only_comparable_change(db):
    asts = _co(db, "ASTS", "AST SpaceMobile, Inc.")
    vod = _co(db, "VOD", "Vodafone Group Plc")
    dt = _co(db, "DTE", "Deutsche Telekom AG")
    for company, prev, last in ((asts, 40.0, 43.0), (vod, 16.0, 15.9), (dt, 30.0, 30.0)):
        _px(db, company, date(2026, 10, 15), prev)
        _px(db, company, date(2026, 10, 16), last)
    # DTE sin cierre del 16: su ultimo cierre es viejo, sin variacion publicada.
    db.query(MarketPrice).filter(MarketPrice.company_id == dt.id, MarketPrice.date == date(2026, 10, 16)).delete()
    db.flush()
    related = related_for_events(db, [(1, asts, TEXT)])[1]
    by_ticker = {r["ticker"]: r for r in related}
    assert related[0]["ticker"] == "ASTS" and related[0]["primary"] is True
    assert by_ticker["VOD"]["price"] == 15.9 and by_ticker["VOD"]["change_pct"] == pytest.approx(-0.62, abs=0.01)
    assert by_ticker["VOD"]["date"] == "2026-10-16" and by_ticker["VOD"]["primary"] is False
    assert by_ticker["DTE"]["price"] == 30.0 and by_ticker["DTE"]["date"] == "2026-10-15"
    assert by_ticker["DTE"]["change_pct"] is None  # cierre viejo: sin variacion inventada


def test_no_strip_when_nothing_else_is_mentioned(db):
    asts = _co(db, "ASTS", "AST SpaceMobile, Inc.")
    assert related_for_events(db, [(7, asts, "AST SpaceMobile launches BlueBird 6")]) == {}


def test_missing_prices_give_none_not_invented_values(db):
    asts = _co(db, "ASTS", "AST SpaceMobile, Inc.")
    _co(db, "VOD", "Vodafone Group Plc")
    related = related_for_events(db, [(3, asts, "AST SpaceMobile and Vodafone Group sign a deal")])[3]
    vod = next(r for r in related if r["ticker"] == "VOD")
    assert vod["price"] is None and vod["change_pct"] is None and vod["date"] is None



def test_single_word_name_needs_adjacent_legal_suffix(db):
    pgr = _co(db, "PGR", "Progressive Corp", exchange="NYSE")
    so = _co(db, "SO", "Southern Company", exchange="NYSE")
    by_name, by_ticker = build_index([pgr, so])
    assert mentioned_companies("Progressive policies on Southern Europe", by_name, by_ticker) == []
    found = {c.ticker for c in mentioned_companies("Progressive Corp and Southern Co. results", by_name, by_ticker)}
    assert found == {"PGR"}


def test_index_is_cached_with_ttl(db):
    _co(db, "AAA", "Alpha Beta Industries Inc")
    nrt._cached_index(db)
    _co(db, "BBB", "Gamma Delta Industries Inc")
    by_name, _ = nrt._cached_index(db)
    assert "gamma delta industries" not in by_name



def _px_unit(db, company, day, close, unit, adj=None):
    db.add(MarketPrice(
        company_id=company.id, date=day, close=close, adj_close=adj, quote_currency=unit, source="yfinance",
    ))


def test_quotes_show_pence_as_pounds_with_the_quote_currency(db):
    """TSCO.L cotiza en GBp: 255 peniques se publican como 2,55 GBP, no «255 GBP»."""
    tsco = _co(db, "TSCO.L", "Tesco PLC", currency="GBP", exchange="LSE")
    _px_unit(db, tsco, date(2026, 10, 15), 250.0, "GBp")
    _px_unit(db, tsco, date(2026, 10, 16), 255.0, "GBp")
    db.flush()
    quote = nrt.quotes_for(db, {tsco.id})[tsco.id]
    assert quote["price"] == pytest.approx(2.55)
    assert quote["currency"] == "GBP"
    assert quote["change_pct"] == pytest.approx(2.0)


def test_quote_change_between_pence_and_pounds_rows_is_a_real_move(db):
    """250 GBp ayer y 2,55 GBP hoy es +2 %, no -98,98 %."""
    tsco = _co(db, "TSCO.L", "Tesco PLC", currency="GBP", exchange="LSE")
    _px_unit(db, tsco, date(2026, 10, 15), 250.0, "GBp")
    _px_unit(db, tsco, date(2026, 10, 16), 2.55, "GBP")
    db.flush()
    assert nrt.quotes_for(db, {tsco.id})[tsco.id]["change_pct"] == pytest.approx(2.0)


def test_quote_change_across_a_split_uses_adjusted_closes(db):
    """Split 4:1 entre sesiones: 200 -> 52 es +4 % (ajustado 50 -> 52), no -74 %."""
    nvda = _co(db, "NVDA", "NVIDIA Corporation")
    _px_unit(db, nvda, date(2026, 10, 15), 200.0, "USD", adj=50.0)
    _px_unit(db, nvda, date(2026, 10, 16), 52.0, "USD", adj=52.0)
    db.flush()
    quote = nrt.quotes_for(db, {nvda.id})[nvda.id]
    assert quote["price"] == 52.0
    assert quote["change_pct"] == pytest.approx(4.0)
