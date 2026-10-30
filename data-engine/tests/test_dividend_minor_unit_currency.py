"""Dividendos de Londres: el registro en peniques (GBX) y la posicion en GBp/GBP.

``DividendIngestionService._known_currency`` guarda los dividendos de Yahoo
cotizados en peniques como ``GBX`` (``"GBp"`` -> ``"GBX"``), mientras que el
ledger conserva la divisa de la operacion (``GBp`` en una compra manual en
peniques, ``GBP`` en IBKR). La comparacion literal ``record.currency ==
position.currency`` descartaba TODOS los dividendos de cualquier posicion en
Londres: la proyeccion la mostraba como «sin datos» y el yield como «sin
dividendos». Es la misma moneda en otra unidad: se convierte sin FX (/100),
igual que ``price_in_currency`` con los precios.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, FXRate, Portfolio, Position
from app.services.dividend_projection_service import DividendProjectionService
from app.services.dividend_records import amount_in_currency


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _setup(db, position_currency: str, record_currency: str = "GBX", amount: str = "10"):
    company = Company(
        ticker="VOD.L", name="Vodafone", exchange="LSE", currency="GBP", sector="Telecom",
        industry="Telecom", company_type="holding", valuation_model="unassigned",
        domicile_country="GB", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    portfolio = Portfolio(name="p", base_currency="EUR")
    db.add(portfolio)
    db.commit()
    db.add(Position(
        portfolio_id=portfolio.id, company_id=company.id, quantity=Decimal("100"),
        average_cost=Decimal("70"), market_price=Decimal("72"), market_value=Decimal("7200"),
        currency=position_currency,
    ))
    today = date.today()
    for days_ago in (40, 220):
        db.add(DividendRecord(
            company_id=company.id, ex_date=today - timedelta(days=days_ago), pay_date=None,
            amount=Decimal(amount), currency=record_currency, source="yahoo",
        ))
    db.add(FXRate(base_currency="EUR", quote_currency="GBP", rate_date=today, rate=Decimal("1.15")))
    db.commit()


def test_gbx_records_feed_a_gbp_pence_position(db):
    _setup(db, position_currency="GBp")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["sin_datos"] == []
    pos = out["positions"][0]
    assert pos["frequency_last_year"] == 2
    # 2 x 10 p x 100 acciones = 2000 p (divisa de la posicion: peniques)
    assert pos["gross_native"] == pytest.approx(2000.0)
    # 2000 p = 20 GBP; 1 GBP = 1,15 EUR -> 23 EUR
    assert pos["gross_base"] == pytest.approx(23.0)


def test_gbx_records_feed_a_gbp_pound_position(db):
    _setup(db, position_currency="GBP")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["sin_datos"] == []
    pos = out["positions"][0]
    # 2 x 0,10 GBP x 100 acciones = 20 GBP (nunca 2000: peniques != libras)
    assert pos["gross_native"] == pytest.approx(20.0)
    assert pos["gross_base"] == pytest.approx(23.0)


def test_other_money_is_still_not_mixed(db):
    _setup(db, position_currency="GBP", record_currency="USD", amount="0.10")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["sin_datos"] == ["VOD.L"]
    assert out["positions"] == []


@pytest.mark.parametrize(
    ("amount", "record", "target", "expected"),
    [
        ("10", "GBX", "GBp", "10"),
        ("10", "GBX", "GBP", "0.10"),
        ("0.10", "GBP", "GBX", "10"),
        ("1.5", "USD", "usd", "1.5"),
        ("25", "ZAc", "ZAR", "0.25"),
        ("1", "USD", "EUR", None),
        ("1", None, "EUR", None),
    ],
)
def test_amount_in_currency_is_unit_conversion_only(amount, record, target, expected):
    got = amount_in_currency(Decimal(amount), record, target)
    assert (got if got is None else got.normalize()) == (None if expected is None else Decimal(expected).normalize())



def test_portfolio_yield_uses_gbx_records_for_gbp_positions(db):
    from app.services.dividend_ingestion_service import DividendIngestionService

    _setup(db, position_currency="GBP")
    position = db.query(Position).one()
    position.market_price = Decimal("72")  # libras
    db.commit()

    out = DividendIngestionService().portfolio_yields(db)

    row = out["positions"][0]
    assert row["skipped_currency_mismatch"] == 0
    # 2 x 10 p = 0,20 GBP por accion; 0,20 / 72 GBP
    assert row["ttm_dividend_per_share"] == pytest.approx(0.20)
    assert row["dividend_yield"] == pytest.approx(0.20 / 72)



def test_same_dividend_in_two_units_is_counted_once(db):
    """FMP en GBP y Yahoo en GBX el mismo dia: es UN dividendo, no dos."""
    _setup(db, position_currency="GBp")
    company = db.query(Company).one()
    for record in db.query(DividendRecord).all():
        db.add(DividendRecord(
            company_id=company.id, ex_date=record.ex_date, pay_date=None,
            amount=Decimal("0.10"), currency="GBP", source="fmp",
        ))
    db.commit()

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["frequency_last_year"] == 2
    assert pos["gross_native"] == pytest.approx(2000.0)  # nunca 4000 p
