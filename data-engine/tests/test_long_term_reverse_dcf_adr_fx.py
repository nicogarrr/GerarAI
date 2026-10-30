"""DCF inverso del modelo a largo plazo con ADR y divisa de reporte distinta.

Ingresos, FCF y acciones vienen del filing (divisa de reporte, acciones
ORDINARIAS); el precio es el del listado (ADR en USD). Antes el solver recibía
el precio del ADR tal cual: crecimiento exigido para un precio en otra divisa
y otra base de acciones. Ahora: precio x FX(listado->reporte) / ratio ADR.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact, MarketPrice
from app.services import long_term_model_service as ltm
from app.services.long_term_model_service import LongTermModelService
from app.valuation.currency import FxQuote

TICKERS = ("LTADR", "LTNOR")


def _cleanup(db) -> None:
    for ticker in TICKERS:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.execute(delete(MarketPrice).where(MarketPrice.company_id == company.id))
            db.delete(company)
    db.commit()


def _company(db, ticker, *, unit, tags, close):
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NYSE", currency="USD",
        sector="Tech", industry="Software", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=tags,
    )
    db.add(company)
    db.flush()
    for year, revenue in ((2022, 800.0), (2023, 900.0), (2024, 1000.0)):
        for metric, value, fact_unit in (
            ("revenue", revenue, unit),
            ("net_income", revenue * 0.15, unit),
            ("free_cash_flow", revenue * 0.20, unit),
            ("net_debt", 100.0, unit),
            ("shares_diluted", 100.0, "shares"),
        ):
            db.add(FinancialFact(
                company_id=company.id, metric=metric, value=Decimal(str(value)), unit=fact_unit,
                period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
                source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
            ))
    db.add(MarketPrice(
        company_id=company.id, date=date(2026, 10, 20), open=Decimal(str(close)),
        high=Decimal(str(close)), low=Decimal(str(close)), close=Decimal(str(close)),
        adj_close=Decimal(str(close)), volume=1000, source="TEST",
    ))
    db.commit()
    return company


@pytest.fixture
def db(monkeypatch):
    def fake_fx(db, from_currency, to_currency, on, **_):
        assert (from_currency.upper(), to_currency.upper()) == ("USD", "CNY")
        return FxQuote("USD", "CNY", 7.0, date(2026, 10, 20), "test", ("USD", "CNY"))

    monkeypatch.setattr(ltm, "resolve_fx", fake_fx, raising=False)
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def test_adr_in_other_currency_solves_on_ordinary_price_in_reporting_currency(db):
    # ADR de 4 ordinarias a 10 USD, hechos en CNY con USD->CNY = 7:
    # precio comparable = 10 * 7 / 4 = 17,5 CNY por ordinaria.
    # (antes el solver recibía 10, el precio del ADR en USD).
    adr = _company(db, "LTADR", unit="CNY", tags=["adr:4"], close=10.0)
    adr_rev = LongTermModelService().build(db, adr)["reverse_dcf"]
    assert adr_rev["market_price"] == pytest.approx(17.5)
    assert adr_rev["price_basis"]["comparable_price"] == pytest.approx(17.5)
    assert adr_rev["price_basis"]["listed_price"] == pytest.approx(10.0)
    assert adr_rev["price_basis"]["adr_ratio"] == 4
    assert adr_rev["price_basis"]["reporting_currency"] == "CNY"


def test_adr_without_ratio_names_the_missing_ratio(db):
    company = _company(db, "LTNOR", unit="USD", tags=["adr"], close=10.0)
    reverse = LongTermModelService().build(db, company)["reverse_dcf"]
    assert reverse["status"] == "insufficient_data"
    assert "adr_ratio" in reverse["missing_inputs"]
    assert "market_price" not in reverse["missing_inputs"]
