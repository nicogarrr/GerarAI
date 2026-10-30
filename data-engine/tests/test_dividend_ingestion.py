"""Dividend ingestion and yield analytics tests."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, Portfolio, Position
from app.services.dividend_ingestion_service import DividendIngestionService


class FakeFMP:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else []
        self.error = error

    async def dividends(self, ticker: str):
        if self.error:
            raise self.error
        return self.payload


class FakeYahoo:
    def __init__(self, payload=None, error=None, currency="USD"):
        self.payload = payload if payload is not None else []
        self.error = error
        self.currency = currency

    async def dividend_events(self, ticker: str):
        if self.error:
            raise self.error
        return {"rows": self.payload, "currency": self.currency}

    async def dividends(self, ticker: str):
        if self.error:
            raise self.error
        return self.payload


_YAHOO_DOWN = FakeYahoo(error=RuntimeError("yahoo down"))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "AAPL", currency: str = "USD") -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency=currency,
        sector="Tech",
        industry="Tech",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _position(db: Session, company: Company, price: float = 200.0, currency: str = "USD") -> Position:
    portfolio = Portfolio(name="p")
    db.add(portfolio)
    db.commit()
    position = Position(
        portfolio_id=portfolio.id,
        company_id=company.id,
        quantity=Decimal("10"),
        average_cost=Decimal("150"),
        market_price=Decimal(str(price)),
        market_value=Decimal(str(10 * price)),
        # El peso de la cartera se calcula SIEMPRE sobre el valor en moneda
        # base. Sin market_value_base la posicion queda fuera del agregado
        # (yield honesto None) en vez de mezclarse con la moneda nativa.
        market_value_base=Decimal(str(10 * price)),
        unrealized_pnl=Decimal("500"),
        realized_pnl=Decimal("0"),
        as_of=date.today(),
        currency=currency,
    )
    db.add(position)
    db.commit()
    return position


PAYLOAD = [
    {
        "symbol": "AAPL",
        "currency": "USD",  # fixture: la fila FMP declara su divisa
        "date": str(date.today()),
        "recordDate": str(date.today()),
        "paymentDate": str(date.today()),
        "declarationDate": str(date.today()),
        "adjDividend": 0.25,
        "dividend": 0.25,
        "yield": 0.5,
        "frequency": "Quarterly",
    }
]


def test_sync_inserts_deduped_records(db):
    service = DividendIngestionService(fmp=FakeFMP(payload=PAYLOAD * 2), yahoo=_YAHOO_DOWN)
    _company(db)
    first = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert first["status"] == "ok"
    assert first["inserted"] == 1 and first["existing"] == 1  # dup within payload skipped
    second = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert second["inserted"] == 0 and second["existing"] == 2  # both payload rows match stored record
    rows = db.scalars(select(DividendRecord)).all()
    assert len(rows) == 1
    assert rows[0].source == "fmp" and rows[0].fetched_at is not None


def test_sync_provider_failure_is_unavailable_not_fabricated(db):
    service = DividendIngestionService(fmp=FakeFMP(error=RuntimeError("402 Payment Required")), yahoo=_YAHOO_DOWN)
    _company(db)
    result = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert result["status"] == "unavailable"
    assert "402" in result["error"]
    assert db.scalars(select(DividendRecord)).all() == []


def test_sync_unknown_company(db):
    service = DividendIngestionService(fmp=FakeFMP(payload=PAYLOAD), yahoo=_YAHOO_DOWN)
    result = asyncio.run(service.sync_company(db, ticker="NOPE"))
    assert result["status"] == "unknown_company"


def test_portfolio_yields_real_math_and_coverage(db):
    company = _company(db)
    _position(db, company, price=200.0)
    # Four quarterly dividends of 0.50 in the last 12 months => TTM 2.00 => 1% yield.
    for month in (1, 4, 7, 10):
        db.add(
            DividendRecord(
                company_id=company.id,
                ex_date=date(date.today().year, month, 15),
                amount=Decimal("0.5"),
                currency="USD",
                source="fmp",
            )
        )
    db.commit()
    result = DividendIngestionService(fmp=FakeFMP(), yahoo=_YAHOO_DOWN).portfolio_yields(db)
    assert result["coverage"]["positions_with_dividend_data"] == 1
    position = result["positions"][0]
    assert position["ttm_dividend_per_share"] == pytest.approx(2.0)
    assert position["dividend_yield"] == pytest.approx(0.01)
    assert result["portfolio_yield"] == pytest.approx(0.01)
    assert result["provenance"]["source_kind"] == "unofficial"


def test_portfolio_yields_honest_nulls_without_data(db):
    company = _company(db, ticker="BRK")
    _position(db, company, price=400.0)
    result = DividendIngestionService(fmp=FakeFMP(), yahoo=_YAHOO_DOWN).portfolio_yields(db)
    position = result["positions"][0]
    assert position["dividend_yield"] is None
    assert position["ttm_dividend_per_share"] is None
    assert result["coverage"]["positions_with_dividend_data"] == 0
    assert result["provenance"]["coverage"] == "unavailable"


def test_currency_mismatch_excluded_from_yield(db):
    company = _company(db)  # USD company
    _position(db, company, price=200.0, currency="EUR")  # position priced in EUR
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date.today(),
            amount=Decimal("0.5"),
            currency="USD",  # dividend declared in USD
            source="fmp",
        )
    )
    db.commit()
    result = DividendIngestionService(fmp=FakeFMP(), yahoo=_YAHOO_DOWN).portfolio_yields(db)
    position = result["positions"][0]
    assert position["skipped_currency_mismatch"] == 1
    # El registro en USD no se mezcla con un precio en EUR. Un 0.0% seria un
    # yield fabricado: la posicion no tiene dividendo en su propia divisa, asi
    # que el estado honesto es "sin dato", no "cero".
    assert position["dividend_yield"] is None


YAHOO_PAYLOAD = [
    {"date": 1750000000, "amount": 0.26},
    {"date": 1740000000, "amount": 0.25},
]


def test_yahoo_is_primary_and_labels_source(db):
    fmp = FakeFMP(payload=PAYLOAD)
    service = DividendIngestionService(fmp=fmp, yahoo=FakeYahoo(payload=YAHOO_PAYLOAD))
    _company(db)
    result = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert result["status"] == "ok" and result["source"] == "yahoo_finance"
    assert result["inserted"] == 2
    rows = db.scalars(select(DividendRecord)).all()
    assert {r.source for r in rows} == {"yahoo_finance"}
    assert all(r.currency == "USD" for r in rows)


def test_yahoo_success_empty_does_not_fall_back(db):
    fmp = FakeFMP(payload=PAYLOAD)
    service = DividendIngestionService(fmp=fmp, yahoo=FakeYahoo(payload=[]))
    _company(db)
    result = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert result["status"] == "ok" and result["source"] == "yahoo_finance"
    assert result["inserted"] == 0
    assert db.scalars(select(DividendRecord)).all() == []


def test_yahoo_failure_falls_back_to_fmp(db):
    service = DividendIngestionService(
        fmp=FakeFMP(payload=PAYLOAD), yahoo=_YAHOO_DOWN
    )
    _company(db)
    result = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert result["status"] == "ok" and result["source"] == "fmp"
    assert result["inserted"] == 1
    rows = db.scalars(select(DividendRecord)).all()
    assert rows[0].source == "fmp"


def test_both_providers_down_is_unavailable(db):
    service = DividendIngestionService(
        fmp=FakeFMP(error=RuntimeError("402")),
        yahoo=FakeYahoo(error=RuntimeError("timeout")),
    )
    _company(db)
    result = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert result["status"] == "unavailable"
    assert db.scalars(select(DividendRecord)).all() == []


def test_sync_portfolio_includes_watchlist_companies(db):
    from app.models.entities import WatchItem

    service = DividendIngestionService(fmp=FakeFMP(payload=PAYLOAD), yahoo=_YAHOO_DOWN)
    _company(db, "AAPL")
    _company(db, "KO")
    _company(db, "MSFT")
    db.add(WatchItem(symbol="KO"))
    db.commit()
    result = asyncio.run(service.sync_portfolio(db))
    synced = {r["ticker"] for r in result["results"] if "ticker" in r}
    assert "KO" in synced and "MSFT" not in synced


_NO_CUR = [{k: v for k, v in PAYLOAD[0].items() if k != "currency"}]


def _no_symbol_guard(monkeypatch):
    # Aislamos la defensa de divisa del guard de simbolo.
    monkeypatch.setattr(DividendIngestionService, "_provider_symbol", lambda self, company: company.ticker)


def _swiss(db: Session):
    company = _company(db, ticker="NOVN", currency="USD")  # divisa de REPORTE
    company.exchange = "SWISS EXCHANGE"
    db.commit()
    return company


def test_yahoo_dividend_currency_is_listing_currency_not_reporting(db):
    """Novartis SIX: company.currency=USD (reporte), dividendo en CHF (meta Yahoo)."""
    _swiss(db)
    service = DividendIngestionService(fmp=FakeFMP(payload=PAYLOAD), yahoo=FakeYahoo(payload=YAHOO_PAYLOAD, currency="CHF"))
    assert asyncio.run(service.sync_company(db, ticker="NOVN"))["inserted"] == 2
    assert {r.currency for r in db.scalars(select(DividendRecord)).all()} == {"CHF"}


def test_yahoo_without_listing_currency_is_not_ingested(db):
    _swiss(db)
    service = DividendIngestionService(fmp=FakeFMP(payload=PAYLOAD), yahoo=FakeYahoo(payload=YAHOO_PAYLOAD, currency=None))
    assert asyncio.run(service.sync_company(db, ticker="NOVN"))["inserted"] == 0
    assert db.scalars(select(DividendRecord)).all() == []


def test_fmp_fallback_never_uses_company_reporting_currency(db):
    """FMP sin divisa en la fila + company USD (reporte) -> no se ingiere."""
    _swiss(db)
    service = DividendIngestionService(fmp=FakeFMP(payload=_NO_CUR), yahoo=_YAHOO_DOWN)
    assert asyncio.run(service.sync_company(db, ticker="NOVN"))["inserted"] == 0
    with_currency = [{**PAYLOAD[0], "currency": "chf"}]
    service = DividendIngestionService(fmp=FakeFMP(payload=with_currency), yahoo=_YAHOO_DOWN)
    assert asyncio.run(service.sync_company(db, ticker="NOVN"))["inserted"] == 1
    assert [r.currency for r in db.scalars(select(DividendRecord)).all()] == ["CHF"]


def test_other_markets_keep_their_own_currency(db):
    for ticker, exch, cur in (("SAP", "XETRA", "EUR"), ("SHEL", "LONDON STOCK EXCHANGE", "GBp"), ("AAPL", "NASDAQ", "USD")):
        company = _company(db, ticker=ticker, currency="USD")
        company.exchange = exch
        db.commit()
    expected = {"SAP": "EUR", "SHEL": "GBX", "AAPL": "USD"}
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(DividendIngestionService, "_provider_symbol", lambda self, company: company.ticker)
    try:
        for ticker, cur in (("SAP", "EUR"), ("SHEL", "GBp"), ("AAPL", "USD")):
            service = DividendIngestionService(fmp=FakeFMP(payload=[]), yahoo=FakeYahoo(payload=YAHOO_PAYLOAD, currency=cur))
            assert asyncio.run(service.sync_company(db, ticker=ticker))["inserted"] == 2
    finally:
        mp.undo()
    got = {}
    for r in db.execute(select(DividendRecord, Company).join(Company, Company.id == DividendRecord.company_id)).all():
        got[r[1].ticker] = r[0].currency
    assert got == expected


def test_empty_company_currency_still_ingests_when_listing_currency_known(db, monkeypatch):
    _no_symbol_guard(monkeypatch)
    _company(db, ticker="BWMX", currency="")
    service = DividendIngestionService(fmp=FakeFMP(payload=[]), yahoo=FakeYahoo(payload=YAHOO_PAYLOAD, currency="USD"))
    assert asyncio.run(service.sync_company(db, ticker="BWMX"))["inserted"] == 2


def test_empty_currency_company_is_stopped_by_symbol_guard(db):
    _company(db, ticker="BWMX", currency="")
    service = DividendIngestionService(fmp=FakeFMP(payload=PAYLOAD), yahoo=FakeYahoo(payload=YAHOO_PAYLOAD))
    result = asyncio.run(service.sync_company(db, ticker="BWMX"))
    assert result["status"] == "no_safe_symbol" and result["inserted"] == 0


def test_unknown_currency_is_observable_as_unknown_not_fresh_ok(db, monkeypatch):
    _no_symbol_guard(monkeypatch)
    _company(db, ticker="BWMX", currency="")
    service = DividendIngestionService(fmp=FakeFMP(payload=[]), yahoo=FakeYahoo(payload=YAHOO_PAYLOAD, currency=None))
    result = asyncio.run(service.sync_company(db, ticker="BWMX"))
    assert result["status"] == "currency_unknown" and result["inserted"] == 0
    assert result["skipped"] == {"unknown_currency": 2} and result["reason"]
    assert db.scalars(select(DividendRecord)).all() == []


def test_portfolio_sync_coverage_is_partial_with_unknown_currency(db, monkeypatch):
    _no_symbol_guard(monkeypatch)
    company = _company(db, ticker="BWMX", currency="")
    _position(db, company)
    service = DividendIngestionService(fmp=FakeFMP(payload=[]), yahoo=FakeYahoo(payload=YAHOO_PAYLOAD, currency=None))
    out = asyncio.run(service.sync_portfolio(db))
    assert out["currency_unknown"] == 1 and out["unavailable"] == 1
    assert out["provenance"]["coverage"] != "ok"


# --- Curacion de filas Yahoo sin reajustar tras un split (caso real: BN 3:2 2025-10-10) ---

from datetime import UTC, datetime  # noqa: E402

from app.models.entities import CorporateAction  # noqa: E402

_SPLIT_EX_DATE = date(2025, 9, 12)


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def _stale_row(db: Session, company: Company, amount: str) -> None:
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=_SPLIT_EX_DATE,
            amount=Decimal(amount),
            currency="USD",
            source="yahoo_finance",
        )
    )
    db.commit()


def _split(db: Session, company: Company, ratio: str = "1.5") -> None:
    db.add(
        CorporateAction(
            company_id=company.id,
            action_type="split",
            effective_date=date(2025, 10, 10),
            ratio=Decimal(ratio),
            source="yahoo_finance",
        )
    )
    db.commit()


def test_split_readjusted_stale_yahoo_row_is_healed(db):
    """BN pago 0.09 pre-split; tras el 3:2 Yahoo sirve 0.06 para el mismo
    ex_date. Con el split ingerido y el proveedor confirmando 0.06 hoy, la
    copia vieja sin reajustar se borra y el grupo deja de ser ambiguo."""
    company = _company(db, "BN")
    _split(db, company)
    _stale_row(db, company, "0.09")
    service = DividendIngestionService(
        fmp=FakeFMP(),
        yahoo=FakeYahoo(payload=[{"date": _epoch(_SPLIT_EX_DATE), "amount": 0.06}]),
    )
    result = asyncio.run(service.sync_company(db, ticker="BN"))
    assert result["status"] == "ok"
    assert result.get("split_readjustments_healed") == 1
    rows = db.scalars(select(DividendRecord)).all()
    assert len(rows) == 1
    assert Decimal(rows[0].amount) == Decimal("0.06")


def test_split_ratio_alone_is_not_evidence(db):
    """Sin split ingerido la relacion 0.09/0.06 = 1.5 no basta: ambas filas
    conviven y resolve_yahoo_events sigue marcando el grupo incierto."""
    company = _company(db, "BN")
    _stale_row(db, company, "0.09")
    service = DividendIngestionService(
        fmp=FakeFMP(),
        yahoo=FakeYahoo(payload=[{"date": _epoch(_SPLIT_EX_DATE), "amount": 0.06}]),
    )
    result = asyncio.run(service.sync_company(db, ticker="BN"))
    assert result["status"] == "ok"
    assert "split_readjustments_healed" not in result
    amounts = {Decimal(r.amount) for r in db.scalars(select(DividendRecord)).all()}
    assert amounts == {Decimal("0.09"), Decimal("0.06")}


def test_ratio_mismatch_leaves_group_untouched(db):
    """Split ingerido pero el proveedor sirve 0.07: 0.09/0.07 no es el factor
    1.5, asi que la discrepancia no se explica y nada se borra."""
    company = _company(db, "BN")
    _split(db, company)
    _stale_row(db, company, "0.09")
    service = DividendIngestionService(
        fmp=FakeFMP(),
        yahoo=FakeYahoo(payload=[{"date": _epoch(_SPLIT_EX_DATE), "amount": 0.07}]),
    )
    result = asyncio.run(service.sync_company(db, ticker="BN"))
    assert result["status"] == "ok"
    assert "split_readjustments_healed" not in result
    amounts = {Decimal(r.amount) for r in db.scalars(select(DividendRecord)).all()}
    assert amounts == {Decimal("0.09"), Decimal("0.07")}


def test_ordinary_plus_special_same_ex_date_survives(db):
    """Dos importes reales el mismo ex_date (ordinaria + especial) reajustados
    por el proveedor: ambos encajan con el proveedor y no se toca nada."""
    company = _company(db, "BN")
    _split(db, company)
    service = DividendIngestionService(
        fmp=FakeFMP(),
        yahoo=FakeYahoo(
            payload=[
                {"date": _epoch(_SPLIT_EX_DATE), "amount": 0.06},
                {"date": _epoch(_SPLIT_EX_DATE), "amount": 0.09},
            ]
        ),
    )
    result = asyncio.run(service.sync_company(db, ticker="BN"))
    assert result["status"] == "ok"
    assert "split_readjustments_healed" not in result
    amounts = {Decimal(r.amount) for r in db.scalars(select(DividendRecord)).all()}
    assert amounts == {Decimal("0.06"), Decimal("0.09")}
