"""F17: refresco intradia de cartera (Yahoo, 15 min) - proveedor y filtro.

El YahooIntradayPriceProvider traduce tickers BME a su simbolo Yahoo (.MC),
tolera tickers sin precio con errores honestos, y MarketRefreshService.refresh
acepta un subconjunto de empresas (solo posiciones) en vez del universo
completo del tenant.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, MarketPrice, Portfolio, Position
from app.services.connectors.ecb import ECBRates
from app.services.market_refresh_service import (
    MarketRefreshService,
    PriceObservation,
    YahooIntradayPriceProvider,
    fetch_intraday_yahoo,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, currency="USD", exchange="NASDAQ"):
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency=currency,
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


class _FakeFXProvider:
    async def fetch(self, *, base_currency, quote_currencies):
        return ECBRates(
            rate_date=date(2026, 9, 25),
            rates={currency: Decimal("1.1") for currency in quote_currencies},
        )


def test_yahoo_provider_maps_bme_suffix_and_reports_missing(db):
    tef = _company(db, "TEF", currency="EUR", exchange="BME")
    asts = _company(db, "ASTS")
    seen_symbols: list[str] = []

    def fake_fetcher(symbols):
        seen_symbols.extend(symbols)
        return {"TEF.MC": (Decimal("4.25"), date(2026, 9, 25))}

    provider = YahooIntradayPriceProvider(fetcher=fake_fetcher)
    observations, errors = asyncio.run(
        provider.fetch([tef, asts], as_of=date(2026, 9, 25))
    )
    assert seen_symbols == ["ASTS", "TEF.MC"]
    assert observations["TEF"].price == Decimal("4.25")
    assert observations["TEF"].source == "yahoo_finance_intraday"
    assert "ASTS" not in observations
    assert errors == [{"ticker": "ASTS", "reason": "yahoo_sin_precio_intradia"}]


def test_yahoo_provider_excludes_unverified_listing(db):
    # Par discordante (bolsa US + divisa no-USD): sin listado local verificado
    # el proveedor no consulta nada - mejor sin precio que el del gemelo/ADR.
    ul = _company(db, "UL", currency="EUR")
    seen_symbols: list[str] = []

    def fake_fetcher(symbols):
        seen_symbols.extend(symbols)
        return {}

    provider = YahooIntradayPriceProvider(fetcher=fake_fetcher)
    observations, errors = asyncio.run(
        provider.fetch([ul], as_of=date(2026, 9, 25))
    )
    assert seen_symbols == []
    assert observations == {}
    assert errors == [{"ticker": "UL", "reason": "yahoo_sin_precio_intradia"}]


def test_yahoo_provider_fetcher_failure_is_one_honest_error(db):
    asts = _company(db, "ASTS")

    def boom(symbols):
        raise RuntimeError("yahoo caido")

    provider = YahooIntradayPriceProvider(fetcher=boom)
    observations, errors = asyncio.run(provider.fetch([asts], as_of=date(2026, 9, 25)))
    assert observations == {}
    assert errors == [{"provider": "yahoo", "reason": "RuntimeError:yahoo caido"}]


def test_fetch_intraday_yahoo_parses_last_close(monkeypatch):
    idx = pd.date_range("2026-09-25 13:30", periods=3, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            ("ASTS", "Close"): [60.0, 61.0, 61.82],
            ("TEF.MC", "Close"): [4.2, 4.21, 4.22],
        },
        index=idx,
    )

    class _FakeYF:
        @staticmethod
        def download(symbols, **kwargs):
            assert symbols == "ASTS TEF.MC"
            assert kwargs["interval"] == "15m"
            return frame

        @staticmethod
        def Ticker(symbol):
            class Ticker:
                fast_info = {"currency": "EUR" if symbol == "TEF.MC" else "USD"}
            return Ticker()

    monkeypatch.setitem(__import__("sys").modules, "yfinance", _FakeYF)
    latest = fetch_intraday_yahoo(["ASTS", "TEF.MC"])
    assert latest["ASTS"] == (Decimal("61.82"), date(2026, 9, 25), "USD")
    assert latest["TEF.MC"] == (Decimal("4.22"), date(2026, 9, 25), "EUR")


def test_refresh_with_companies_filter_only_fetches_positions_universe(db):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    held = _company(db, "ASTS")
    not_held = _company(db, "MSFT")
    db.add(Position(
        company_id=held.id, quantity=Decimal("10"), currency="USD",
        market_price=Decimal("50"), market_value=Decimal("500"),
    ))
    db.commit()

    fetched: list[str] = []

    class _RecordingProvider:
        async def fetch(self, companies, *, as_of):
            fetched.extend(company.ticker for company in companies)
            return (
                {
                    "ASTS": PriceObservation(
                        ticker="ASTS", price=Decimal("61.82"),
                        price_date=as_of, source="fake_intraday",
                    )
                },
                [],
            )

    service = MarketRefreshService(
        price_provider=_RecordingProvider(), fx_provider=_FakeFXProvider()
    )
    result = asyncio.run(
        service.refresh(db, as_of=date(2026, 9, 25), companies=[held])
    )
    assert fetched == ["ASTS"]
    price = db.scalar(select(MarketPrice).where(MarketPrice.company_id == held.id))
    assert price.close == Decimal("61.82")
    assert price.source == "fake_intraday"
    assert db.scalar(select(MarketPrice).where(MarketPrice.company_id == not_held.id)) is None
    prices_step = result["stages"][0]
    assert prices_step["status"] == "ok"
    assert prices_step["updated"] == 1


def test_fetch_intraday_yahoo_remembers_listing_currency(monkeypatch):
    """La divisa del listado (``fast_info``, una peticion por simbolo) no se
    pide en cada pasada de 15 min: se recuerda; un fallo no se recuerda."""
    from app.services import market_refresh_service as mrs

    getattr(mrs, "_listing_currency_cache", {}).clear()
    idx = pd.date_range("2026-09-25 13:30", periods=2, freq="15min", tz="UTC")
    frame = pd.DataFrame({("ASTS", "Close"): [60.0, 61.0], ("NOCUR", "Close"): [1.0, 2.0]}, index=idx)
    lookups: list[str] = []

    class _FakeYF:
        @staticmethod
        def download(symbols, **kwargs):
            return frame

        @staticmethod
        def Ticker(symbol):  # noqa: N802 - API de yfinance
            lookups.append(symbol)

            class Ticker:
                fast_info = {"currency": "USD" if symbol == "ASTS" else None}

            return Ticker()

    monkeypatch.setitem(__import__("sys").modules, "yfinance", _FakeYF)
    first = fetch_intraday_yahoo(["ASTS", "NOCUR"])
    second = fetch_intraday_yahoo(["ASTS", "NOCUR"])
    assert first["ASTS"][2] == "USD" and second["ASTS"][2] == "USD"
    assert second["NOCUR"][2] is None
    # ASTS una sola vez; NOCUR (sin divisa) se reintenta en cada pasada.
    assert lookups == ["ASTS", "NOCUR", "NOCUR"]
    getattr(mrs, "_listing_currency_cache", {}).clear()
