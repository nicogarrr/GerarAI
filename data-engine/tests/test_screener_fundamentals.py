"""Hermetic tests: sourced pe/pb/roe for /api/screeners/real.

No network. Ratios come from SEC/ESEF facts plus the latest stored daily
close; missing, stale, seed or cross-year inputs must stay null.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, CorporateAction, FinancialFact, MarketPrice, Tenant
from app.services.screener_fundamentals import load_screener_ratios

TODAY = date(2026, 9, 25)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, Company.__table__, FinancialFact.__table__, MarketPrice.__table__, CorporateAction.__table__],
    )
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "AAPL", currency: str = "USD") -> Company:
    row = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency=currency,
        sector="Technology", industry="Hardware", company_type="operating",
        valuation_model="standard_dcf",
    )
    db.add(row)
    db.flush()
    return row


def _fact(db: Session, company: Company, metric: str, value: str, unit: str, *, year: int = 2024, source: str = "SEC", quarter: str | None = "FY", period: str | None = None) -> FinancialFact:
    row = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(value), unit=unit,
        period=period or f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter=quarter, source_type=source, is_reported=True,
    )
    db.add(row)
    db.flush()
    return row


def _price(db: Session, company: Company, close: str, *, day: date | None = None, source: str = "yahoo") -> MarketPrice:
    row = MarketPrice(
        company_id=company.id, date=day or TODAY, close=Decimal(close),
        adj_close=Decimal(close), source=source,
    )
    db.add(row)
    db.flush()
    return row


def test_ratios_from_sec_facts(db):
    company = _company(db)
    _price(db, company, "180")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _fact(db, company, "total_equity", "50000000000", "USD")
    _fact(db, company, "shares_diluted", "15000000000", "shares")
    _fact(db, company, "net_income", "10000000000", "USD")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(30.0)
    assert result["pb"] == pytest.approx(54.0)
    assert result["roe"] == pytest.approx(20.0)
    assert result["ratioProvenance"]["price"]["source"] == "yahoo"
    assert result["ratioProvenance"]["facts"]["pe"]["source"] == "SEC"


def test_annual_facts_with_null_quarter_still_load(db):
    company = _company(db)
    _price(db, company, "180")
    _fact(db, company, "eps_diluted", "6", "USD/share", quarter=None, period="FY")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(30.0)


def test_missing_facts_stay_null(db):
    company = _company(db)
    _price(db, company, "180")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result == {"pe": None, "pb": None, "roe": None, "has_fundamentals": False}


def test_seed_facts_and_seed_prices_ignored(db):
    company = _company(db)
    _price(db, company, "180", source="seed")
    _fact(db, company, "eps_diluted", "6", "USD/share", source="seed")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result == {"pe": None, "pb": None, "roe": None, "has_fundamentals": False}


def test_cross_fiscal_years_never_combined(db):
    company = _company(db)
    _price(db, company, "180")
    _fact(db, company, "total_equity", "50000000000", "USD", year=2024)
    _fact(db, company, "shares_diluted", "15000000000", "shares", year=2023)
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pb"] is None


def test_stale_price_and_old_facts_ignored(db):
    company = _company(db)
    _price(db, company, "180", day=TODAY - timedelta(days=10))
    _fact(db, company, "eps_diluted", "6", "USD/share", year=2022)
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result == {"pe": None, "pb": None, "roe": None, "has_fundamentals": False}


def test_currency_mismatch_and_negative_eps_rejected(db):
    company = _company(db)
    _price(db, company, "180")
    _fact(db, company, "eps_diluted", "6", "iso4217:EUR/xbrli:shares")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] is None
    db.delete(result and db.get(FinancialFact, result and 1) or FinancialFact(id=1)) if False else None
    db.rollback()


def test_negative_eps_yields_null_pe(db):
    company = _company(db)
    _price(db, company, "180")
    _fact(db, company, "eps_diluted", "-2", "USD/share")
    assert load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]["pe"] is None


def test_esef_units_normalize_for_european_company(db):
    company = _company(db, ticker="SAN", currency="EUR")
    _price(db, company, "5")
    _fact(db, company, "eps_diluted", "0.5", "iso4217:EUR/xbrli:shares", source="ESEF")
    _fact(db, company, "total_equity", "100000000000", "iso4217:EUR", source="ESEF")
    _fact(db, company, "net_income", "9000000000", "iso4217:EUR", source="ESEF")
    result = load_screener_ratios(db, {"SAN"}, today=TODAY)["SAN"]
    assert result["pe"] == pytest.approx(10.0)
    assert result["roe"] == pytest.approx(9.0)
    assert result["pb"] is None  # hueco honesto ESEF: sin shares_diluted


def test_route_items_merge_ratios(monkeypatch):
    from app.api.routes import screeners

    monkeypatch.setattr(screeners, "_REAL_UNIVERSE", [("AAPL", "Apple", "Technology")])
    monkeypatch.setattr(screeners, "_load_universe_from_db", lambda: {})
    monkeypatch.setattr(screeners, "_load_screener_ratios", lambda **_: {"AAPL": {"pe": 30.0, "pb": 54.0, "roe": 20.0}})
    monkeypatch.setattr(screeners, "_fetch_quote", lambda client, symbol, vendor: {
        "price": 180.0, "change": 1.0, "changePercent": 0.56, "volume": 1000.0, "prevClose": 179.0, "asOf": 1,
    })
    monkeypatch.setattr(screeners, "_fetch_profile", lambda client, symbol, vendor: {
        "name": "Apple Inc", "marketCap": 2.8e12, "sector": "Technology", "exchange": "NASDAQ",
    })
    items = screeners._refetch_real_items(vendor="finnhub")
    assert items[0]["pe"] == 30.0 and items[0]["pb"] == 54.0 and items[0]["roe"] == 20.0
    assert items[0]["beta"] is None


def test_route_items_keep_nulls_without_facts(monkeypatch):
    from app.api.routes import screeners

    monkeypatch.setattr(screeners, "_REAL_UNIVERSE", [("AAPL", "Apple", "Technology")])
    monkeypatch.setattr(screeners, "_load_universe_from_db", lambda: {})
    monkeypatch.setattr(screeners, "_load_screener_ratios", lambda **_: {})
    monkeypatch.setattr(screeners, "_fetch_quote", lambda client, symbol, vendor: {
        "price": 180.0, "change": 1.0, "changePercent": 0.56, "volume": 1000.0, "prevClose": 179.0, "asOf": 1,
    })
    monkeypatch.setattr(screeners, "_fetch_profile", lambda client, symbol, vendor: {
        "name": "Apple Inc", "marketCap": 2.8e12, "sector": "Technology", "exchange": "NASDAQ",
    })
    items = screeners._refetch_real_items(vendor="finnhub")
    assert items[0]["pe"] is None and items[0]["pb"] is None and items[0]["roe"] is None


def test_live_price_fallback_when_no_market_price_in_db(db):
    company = _company(db, "GOOGL")
    _fact(db, company, "eps_diluted", "8", "USD/share")
    out = load_screener_ratios(
        db,
        {"GOOGL"},
        today=TODAY,
        live_prices={"GOOGL": {"price": 160.0, "source": "yahoo_finance", "as_of": "2026-09-25T20:00:00Z"}},
    )
    metrics = out["GOOGL"]
    assert metrics["pe"] == 20.0
    assert metrics["ratioProvenance"]["price"] == {
        "source": "yahoo_finance",
        "date": "2026-09-25T20:00:00Z",
        "id": None,
    }
    assert metrics["ratioProvenance"]["facts"]["pe"]["source"] == "SEC"


def test_db_price_wins_over_live_price(db):
    company = _company(db, "AAPL")
    _price(db, company, "100")
    _fact(db, company, "eps_diluted", "5", "USD/share")
    out = load_screener_ratios(
        db,
        {"AAPL"},
        today=TODAY,
        live_prices={"AAPL": {"price": 300.0, "source": "yahoo_finance", "as_of": None}},
    )
    assert out["AAPL"]["pe"] == 20.0
    assert out["AAPL"]["ratioProvenance"]["price"]["source"] == "yahoo"


def test_invalid_or_missing_live_price_stays_null(db):
    company = _company(db, "CRM")
    _fact(db, company, "eps_diluted", "8", "USD/share")
    for live in (
        {"CRM": {"price": 0, "source": "yahoo_finance", "as_of": None}},
        {"CRM": {"price": None, "source": "yahoo_finance", "as_of": None}},
        {"CRM": {"price": "not-a-number", "source": "yahoo_finance", "as_of": None}},
    ):
        out = load_screener_ratios(db, {"CRM"}, today=TODAY, live_prices=live)
        assert out["CRM"]["pe"] is None


def test_live_price_wins_when_newer_than_local(db):
    company = _company(db, "AAPL")
    _price(db, company, "100", day=TODAY - timedelta(days=1), source="finnhub")
    _fact(db, company, "eps_diluted", "5", "USD/share")
    out = load_screener_ratios(
        db, {"AAPL"}, today=TODAY,
        live_prices={"AAPL": {"price": 160.0, "source": "yahoo_finance", "as_of": f"{TODAY.isoformat()}T15:00:00Z"}},
    )
    assert out["AAPL"]["pe"] == 32.0
    assert out["AAPL"]["ratioProvenance"]["price"] == {
        "source": "yahoo_finance", "date": f"{TODAY.isoformat()}T15:00:00Z", "id": None,
    }


def test_live_price_wins_on_same_date_as_local(db):
    company = _company(db, "AAPL")
    _price(db, company, "100", day=TODAY, source="finnhub")
    _fact(db, company, "eps_diluted", "5", "USD/share")
    out = load_screener_ratios(
        db, {"AAPL"}, today=TODAY,
        live_prices={"AAPL": {"price": 160.0, "source": "yahoo_finance", "as_of": f"{TODAY.isoformat()}T15:00:00Z"}},
    )
    assert out["AAPL"]["pe"] == 32.0
    assert out["AAPL"]["ratioProvenance"]["price"]["source"] == "yahoo_finance"


def test_older_live_price_loses_to_fresher_local(db):
    company = _company(db, "AAPL")
    _price(db, company, "100", day=TODAY, source="finnhub")
    _fact(db, company, "eps_diluted", "5", "USD/share")
    out = load_screener_ratios(
        db, {"AAPL"}, today=TODAY,
        live_prices={"AAPL": {"price": 300.0, "source": "yahoo_finance", "as_of": f"{(TODAY - timedelta(days=1)).isoformat()}T20:00:00Z"}},
    )
    assert out["AAPL"]["pe"] == 20.0
    assert out["AAPL"]["ratioProvenance"]["price"]["source"] == "finnhub"


def test_live_without_comparable_date_loses_to_local(db):
    company = _company(db, "AAPL")
    _price(db, company, "100", day=TODAY, source="finnhub")
    _fact(db, company, "eps_diluted", "5", "USD/share")
    out = load_screener_ratios(
        db, {"AAPL"}, today=TODAY,
        live_prices={"AAPL": {"price": 300.0, "source": "yahoo_finance", "as_of": "no-es-fecha"}},
    )
    assert out["AAPL"]["pe"] == 20.0
    assert out["AAPL"]["ratioProvenance"]["price"]["source"] == "finnhub"


def test_has_fundamentals_true_with_revenue_and_shares(db):
    """QA inicio DCF: revenue + acciones diluidas SEC/ESEF marcan la candidata
    como prioritaria para la sonda DCF de la tarjeta de inicio."""
    company = _company(db, "AAPL")
    _price(db, company, "100")
    _fact(db, company, "revenue", "1000", "USD", year=2025)
    _fact(db, company, "shares_diluted", "100", "shares", year=2025)
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["has_fundamentals"] is True


def test_has_fundamentals_false_without_revenue(db):
    company = _company(db, "AAPL")
    _price(db, company, "100")
    _fact(db, company, "net_income", "50", "USD", year=2025)
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["has_fundamentals"] is False


def test_has_fundamentals_false_for_quarterly_only(db):
    company = _company(db, "AAPL")
    _price(db, company, "100")
    _fact(db, company, "revenue", "250", "USD", year=2025, quarter="Q1", period="2025-03-31:Q1")
    _fact(db, company, "shares_diluted", "100", "shares", year=2025, quarter="Q1", period="2025-03-31:Q1")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["has_fundamentals"] is False


def test_adr_ratios_use_price_per_ordinary_share(db):
    """ADR 2:1 que reporta en USD (etiqueta adr:2). Hechos por ordinaria.

    Cálculo independiente: ADR a 70 -> 35 por ordinaria; PER = 35 / 3,5 = 10
    (en main 70 / 3,5 = 20); libros/ordinaria = 200 / 20 = 10 -> P/B = 3,5
    (en main 7). El ROE no depende del precio: 30 / 200 = 15 %.
    """
    company = _company(db, "SHEL")
    company.factor_tags = ["adr:2"]
    db.flush()
    _price(db, company, "70")
    _fact(db, company, "eps_diluted", "3.5", "USD/share")
    _fact(db, company, "total_equity", "200", "USD")
    _fact(db, company, "shares_diluted", "20", "shares")
    _fact(db, company, "net_income", "30", "USD")
    result = load_screener_ratios(db, {"SHEL"}, today=TODAY)["SHEL"]
    assert result["pe"] == pytest.approx(10.0)
    assert result["pb"] == pytest.approx(3.5)
    assert result["roe"] == pytest.approx(15.0)
    assert result["ratioProvenance"]["price"]["adr_ratio"] == 2


def test_adr_tag_without_ratio_has_no_price_ratios(db):
    company = _company(db, "XADR")
    company.factor_tags = ["adr"]
    db.flush()
    _price(db, company, "70")
    _fact(db, company, "eps_diluted", "3.5", "USD/share")
    result = load_screener_ratios(db, {"XADR"}, today=TODAY)["XADR"]
    assert result["pe"] is None
    assert result["pb"] is None
