"""Mutation testing (docs/testing/mutation.md): asserts que mutmut mostró ausentes
en PortfolioSnapshotService.capture.

Supervivientes que cubren: la suma de varias posiciones (``+=`` -> ``=``), el
precio 0 o sin tipo de cambio como «sin valorar» (no 0 € ni valor inventado) y
el detalle exacto de ``missing_pricing`` que leen la API y el chat.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, Company, Position
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_snapshot_service import PortfolioSnapshotService

TODAY = date.today()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency="EUR",
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


def _position(db: Session, ticker: str, *, qty: str, price: str, currency: str = "EUR") -> Position:
    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.commit()
    position = Position(
        portfolio_id=portfolio.id,
        company_id=_company(db, ticker).id,
        quantity=Decimal(qty),
        market_price=Decimal(price),
        currency=currency,
        as_of=TODAY,
    )
    db.add(position)
    db.commit()
    return position


def test_varias_posiciones_se_suman_todas(db):
    _position(db, "AAA", qty="10", price="100")
    _position(db, "BBB", qty="2", price="50")
    _position(db, "CCC", qty="1", price="7.5")
    snap = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snap.positions_value_base == Decimal("1107.5")
    assert snap.total_value_base == Decimal("1107.5")
    assert snap.metadata_["missing_pricing"] == []


def test_precio_cero_es_sin_valorar_y_se_reporta(db):
    ok = _position(db, "AAA", qty="10", price="100")
    zero = _position(db, "ZZZ", qty="5", price="0")
    snap = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snap.positions_value_base == Decimal("1000")
    assert snap.pricing_coverage == Decimal("0.5")
    assert snap.metadata_["missing_pricing"] == [
        {"company_id": zero.company_id, "currency": "EUR", "valuation_date": TODAY.isoformat()}
    ]
    assert ok.company_id != zero.company_id


def test_sin_tipo_de_cambio_no_se_inventa_valor(db):
    _position(db, "AAA", qty="10", price="100")
    usd = _position(db, "USD1", qty="3", price="20", currency="USD")  # sin tasa USD->EUR
    db.add(CashBalance(currency="GBP", balance=Decimal("40"), as_of=TODAY))  # sin tasa GBP
    db.commit()
    snap = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snap.positions_value_base == Decimal("1000")
    assert snap.cash_value_base == Decimal("0")
    missing = snap.metadata_["missing_pricing"]
    assert {"company_id": usd.company_id, "currency": "USD", "valuation_date": TODAY.isoformat()} in missing
    assert {"cash_currency": "GBP", "valuation_date": TODAY.isoformat()} in missing
    assert len(missing) == 2
