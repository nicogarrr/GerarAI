"""Contrato del backfill de quote_currency (radar DCA: currency_mismatch).

La divisa sale SOLO del proveedor (Yahoo chart meta), nunca inferida; solo se
tocan filas NULL (idempotente); dry_run no escribe; un fallo del proveedor en
un ticker no frena al resto.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice
from app.services.market_price_currency_backfill import backfill_quote_currency


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(ticker=ticker, name=ticker, exchange="UNKNOWN", currency="USD",
            sector="", industry="", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    return company


def _bar(db: Session, company: Company, day: date, currency, source="yfinance") -> MarketPrice:
    bar = MarketPrice(
        company_id=company.id, date=day, open=Decimal("10"), high=Decimal("10"),
        low=Decimal("10"), close=Decimal("10"), adj_close=Decimal("10"),
        volume=1000, source=source, quote_currency=currency,
    )
    db.add(bar)
    db.commit()
    return bar


class _Fetcher:
    """fetch_currency inyectable: mapa ticker -> divisa (o excepcion)."""

    def __init__(self, currencies):
        self.currencies = currencies
        self.calls = []

    async def __call__(self, ticker: str):
        self.calls.append(ticker)
        value = self.currencies.get(ticker)
        if isinstance(value, Exception):
            raise value
        return value


async def _no_sleep(_seconds: float) -> None:
    return None


def _test(db, currencies, **kwargs):
    fetcher = _Fetcher(currencies)
    return fetcher, backfill_quote_currency(db, fetch_currency=fetcher, sleep=_no_sleep, **kwargs)


def test_rellena_solo_filas_null_con_la_divisa_del_proveedor(db):
    msft = _company(db, "MSFT")
    _bar(db, msft, date(2026, 10, 27), None)
    _bar(db, msft, date(2026, 10, 28), None)
    _bar(db, msft, date(2026, 10, 29), "USD")  # dato real: intocable

    fetcher, coro = _test(db, {"MSFT": "USD"})
    result = asyncio.run(coro)

    assert result["rows_updated"] == 2 and result["companies_updated"] == 1
    assert fetcher.calls == ["MSFT"]  # 1 llamada por empresa, no por fila
    units = [u for (u,) in db.execute(select(MarketPrice.quote_currency).order_by(MarketPrice.date)).all()]
    assert units == ["USD", "USD", "USD"]


def test_nunca_infiere_si_el_proveedor_no_da_divisa(db):
    googl = _company(db, "GOOGL")
    _bar(db, googl, date(2026, 10, 28), None)

    _, coro = _test(db, {"GOOGL": None})
    result = asyncio.run(coro)

    assert result["rows_updated"] == 0
    assert result["unresolved"] == [{"ticker": "GOOGL", "reason": "provider_without_currency"}]
    assert db.scalar(select(MarketPrice.quote_currency)) is None


def test_idempotente_segunda_pasada_no_toca_nada(db):
    msft = _company(db, "MSFT")
    _bar(db, msft, date(2026, 10, 28), None)

    _, coro = _test(db, {"MSFT": "USD"})
    asyncio.run(coro)
    fetcher2, coro2 = _test(db, {"MSFT": "USD"})
    result2 = asyncio.run(coro2)

    assert result2["companies_scanned"] == 0 and result2["rows_updated"] == 0
    assert fetcher2.calls == []  # sin NULLs no hay ni llamada al proveedor


def test_dry_run_cuenta_sin_escribir(db):
    msft = _company(db, "MSFT")
    _bar(db, msft, date(2026, 10, 28), None)

    _, coro = _test(db, {"MSFT": "USD"}, dry_run=True)
    result = asyncio.run(coro)

    assert result["dry_run"] is True and result["rows_updated"] == 1
    assert db.scalar(select(MarketPrice.quote_currency)) is None  # rollback


def test_un_ticker_caido_no_frena_al_resto(db):
    aapl = _company(db, "AAPL")
    msft = _company(db, "MSFT")
    _bar(db, aapl, date(2026, 10, 28), None)
    _bar(db, msft, date(2026, 10, 28), None)

    _, coro = _test(db, {"AAPL": RuntimeError("HTTP 429"), "MSFT": "USD"})
    result = asyncio.run(coro)

    assert result["rows_updated"] == 1
    assert result["unresolved"] == [{"ticker": "AAPL", "reason": "fetch_error: RuntimeError"}]


def test_divisa_sucia_del_proveedor_se_rechaza(db):
    msft = _company(db, "MSFT")
    _bar(db, msft, date(2026, 10, 28), None)

    _, coro = _test(db, {"MSFT": "USD; DROP TABLE market_prices"})
    result = asyncio.run(coro)

    assert result["rows_updated"] == 0
    assert db.scalar(select(MarketPrice.quote_currency)) is None


def test_pacing_pausa_entre_llamadas_al_proveedor(db):
    a = _company(db, "AAPL")
    b = _company(db, "MSFT")
    _bar(db, a, date(2026, 10, 28), None)
    _bar(db, b, date(2026, 10, 28), None)
    pauses = []

    async def spy_sleep(seconds: float) -> None:
        pauses.append(seconds)

    fetcher = _Fetcher({"AAPL": "USD", "MSFT": "USD"})
    asyncio.run(backfill_quote_currency(db, fetch_currency=fetcher, pause_seconds=1.5, sleep=spy_sleep))

    assert pauses == [1.5]  # pausa ENTRE llamadas, no antes de la primera
    assert fetcher.calls == ["AAPL", "MSFT"]
