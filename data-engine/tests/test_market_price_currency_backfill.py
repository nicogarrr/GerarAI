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


def test_dry_run_no_mantiene_transaccion_abierta_durante_la_red(db):
    """Regresion prod 31-oct-2026: dry-run de 1000 tickers, ~27 min de red con
    la transaccion de la lectura inicial abierta -> IdleInTransactionSessionTimeout.
    Al llegar la llamada de red no puede haber transaccion viva."""
    aapl = _company(db, "AAPL")
    msft = _company(db, "MSFT")
    _bar(db, aapl, date(2026, 10, 28), None)
    _bar(db, msft, date(2026, 10, 28), None)
    estados = []

    async def espia(ticker: str):
        estados.append(db.in_transaction())
        return "USD"

    result = asyncio.run(backfill_quote_currency(
        db, fetch_currency=espia, dry_run=True, sleep=_no_sleep))

    assert result["companies_updated"] == 2
    assert estados == [False, False]  # red sin transaccion abierta, siempre


def test_commit_acotado_por_empresa(db):
    """Cada empresa commitea al terminar la suya: un corte a mitad no pierde
    el trabajo ya hecho ni mantiene una transaccion viva entre tickers."""
    aapl = _company(db, "AAPL")
    msft = _company(db, "MSFT")
    _bar(db, aapl, date(2026, 10, 28), None)
    _bar(db, msft, date(2026, 10, 28), None)
    commits = []
    commit_real = db.commit

    def espia_commit():
        commits.append(1)
        return commit_real()

    db.commit = espia_commit
    result = asyncio.run(backfill_quote_currency(
        db, fetch_currency=_Fetcher({"AAPL": "USD", "MSFT": "EUR"}), sleep=_no_sleep))

    assert result["companies_updated"] == 2
    assert len(commits) == 2  # un commit por empresa, no uno global al final


def test_fallo_de_bd_en_un_ticker_no_aborta_el_barrido(db):
    aapl = _company(db, "AAPL")
    msft = _company(db, "MSFT")
    _bar(db, aapl, date(2026, 10, 28), None)
    _bar(db, msft, date(2026, 10, 28), None)
    execute_real = db.execute
    llamadas = {"n": 0}

    def execute_fallido(*args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 2:  # 1=lectura de objetivos, 2=primer UPDATE
            raise RuntimeError("IdleInTransactionSessionTimeout")
        return execute_real(*args, **kwargs)

    db.execute = execute_fallido
    result = asyncio.run(backfill_quote_currency(
        db, fetch_currency=_Fetcher({"AAPL": "USD", "MSFT": "EUR"}), sleep=_no_sleep))

    assert result["companies_updated"] == 1
    assert result["unresolved"] == [{"ticker": "AAPL", "reason": "db_error: RuntimeError"}]
    unidades = dict(
        db.execute(select(Company.ticker, MarketPrice.quote_currency)
                   .join(Company, Company.id == MarketPrice.company_id)).all()
    )
    assert unidades == {"AAPL": None, "MSFT": "EUR"}  # el siguiente ticker siguió


def test_log_de_progreso_por_ticker(db, caplog):
    aapl = _company(db, "AAPL")
    msft = _company(db, "MSFT")
    _bar(db, aapl, date(2026, 10, 28), None)
    _bar(db, msft, date(2026, 10, 28), None)

    with caplog.at_level("INFO", logger="backfill_market_price_currency"):
        asyncio.run(backfill_quote_currency(
            db, fetch_currency=_Fetcher({"AAPL": "USD", "MSFT": "EUR"}), sleep=_no_sleep))

    lineas = [r.getMessage() for r in caplog.records if r.name == "backfill_market_price_currency"]
    assert any("[1/2] AAPL" in linea for linea in lineas)
    assert any("[2/2] MSFT" in linea for linea in lineas)
