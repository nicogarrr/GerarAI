"""Shared quote-unit regressions. Synthetic SQLite only; no provider traffic."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.market import market_changes, market_movers
from app.models.entities import Base, Company, FinancialFact, MarketPrice
from app.services.historical_valuation_service import HistoricalValuationService
from app.services.market_change import compute_session_changes, ticker_close_change
from app.services.sale_hypothetical import HypoLot, latest_quote, simulate_hypothetical_sale


@pytest.fixture
def sample():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(
            ticker="DEMO.L",
            name="Synthetic",
            exchange="LSE",
            currency="GBP",
            sector="Test",
            industry="Test",
            company_type="holding",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        yield db, company


def close(db, company, day, value, unit):
    row = MarketPrice(
        company_id=company.id,
        date=day,
        close=Decimal(value),
        quote_currency=unit,
        open=Decimal(value),
        high=Decimal(value),
        low=Decimal(value),
        adj_close=Decimal(value),
        source="yfinance",
        volume=100000,
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("last,unit", [("43", "GBP"), ("4300", "GBX"), ("4300", "GBp")])
def test_movers_and_ticker_normalize_each_close(sample, last, unit):
    db, company = sample
    close(db, company, date(2026, 10, 26), "4200", "GBX")
    close(db, company, date(2026, 10, 27), last, unit)
    rows, _, _ = compute_session_changes(db)
    assert rows[0]["currency"] == "GBP"
    assert rows[0]["price"] == 43
    assert rows[0]["previous_close"] == 42
    assert rows[0]["change_pct"] == 2.38
    ticker = ticker_close_change(db, company.id)
    assert ticker["close"] == 43
    assert ticker["change_percent"] == pytest.approx(100 / 42)
    item = market_changes(tickers=company.ticker, db=db)["items"][company.ticker]
    assert item["currency"] == "GBP"
    assert item["price"] == 43


@pytest.mark.parametrize("unit", [None, "USD"])
def test_ambiguous_or_incompatible_prices_do_not_rank_or_simulate(sample, unit):
    db, company = sample
    close(db, company, date(2026, 10, 26), "4200", "GBX")
    close(db, company, date(2026, 10, 27), "4300", unit)
    assert latest_quote(db, company) is None
    assert ticker_close_change(db, company.id) is None
    row = compute_session_changes(db)[0][0]
    assert row["price"] is None and row["change_pct"] is None
    result = market_movers(db=db, limit=10)
    assert not result["gainers"] and not result["most_active"]


def test_hypothetical_quote_is_major_currency_before_fx(sample, monkeypatch):
    db, company = sample
    company.currency = "GBX"
    close(db, company, date(2026, 10, 27), "200", "GBp")
    import app.services.sale_hypothetical as module
    from app.services.portfolio_fx_service import PortfolioFXService

    monkeypatch.setattr(PortfolioFXService, "fx_table", lambda *a, **kw: {})
    monkeypatch.setattr(module, "_rate_not_older_than", lambda *a, **kw: Decimal("1.2"))
    result = simulate_hypothetical_sale(
        db,
        lots=[HypoLot(Decimal(10), Decimal(1), "GBP", date(2025, 1, 1))],
        question="vendo 10 acciones",
        company=company,
        today=date(2026, 10, 27),
    )
    assert result.sale_currency == "GBP"
    assert result.sale_price == 2
    assert result.value_eur == 24
    assert result.gain_eur == 12


@pytest.mark.parametrize(
    "fact_unit,expected", [("GBP/share", Decimal(10)), ("USD/share", None), (None, None)]
)
def test_historical_price_and_eps_must_have_compatible_units(sample, fact_unit, expected):
    db, company = sample
    close(db, company, date(2024, 12, 31), "1000", "GBX")
    db.add(
        FinancialFact(
            company_id=company.id,
            metric="eps_diluted",
            value=Decimal(1),
            unit=fact_unit,
            fiscal_year=2024,
            period="2024:FY",
            filed=date(2025, 2, 1),
            source_type="SEC",
        )
    )
    db.commit()
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 10, 27))
    assert result["currency"] == "GBP"
    assert result["series"][0]["price"] == 10
    assert result["series"][0]["pe"] == expected


@pytest.mark.parametrize("quote_unit,expected", [("GBX", 100.0), ("GBP", 1.0), ("USD", None)])
def test_extended_quote_scales_absolute_change_into_response_unit(sample, monkeypatch, quote_unit, expected):
    import asyncio

    from app.api.routes import companies
    from app.services.extended_quote_service import ExtendedQuote

    db, company = sample
    close(db, company, date(2026, 10, 26), "4200", "GBX")
    close(db, company, date(2026, 10, 27), "43", "GBP")
    quote = ExtendedQuote(
        ticker=company.ticker, status="available", session="cerrado", price=4300, currency=quote_unit, fetched_at=1
    )

    async def get_quote(ticker):
        return quote

    async def inline(fn):
        return fn()

    monkeypatch.setattr(companies, "run_in_threadpool", inline)
    monkeypatch.setattr(companies.extended_quote_service, "get", get_quote)
    result = asyncio.run(companies.company_extended_quote(company.ticker, db=db))
    assert result.close_change == expected
    if expected is not None:
        assert result.close_change_percent == pytest.approx(100 / 42)
