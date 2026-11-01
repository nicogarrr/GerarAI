"""El precio del modelo de valoración no es el de tu propia compra.

``resolve_model_price`` («el precio real más fresco») tomaba el mark de una
posición abierta cuando no había cierre guardado. En una posición del ledger
sin cotización ese mark es el precio de tu última operación (auditoría A3,
«sin cotización real» en /positions): el margen de seguridad y el DCF inverso
de la ficha se calculaban contra lo que pagaste, como si fuera el mercado.
Un mark de broker (IBKR) sigue valiendo.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.valuation_service import resolve_model_price


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _buy(db: Session, ticker: str) -> Company:
    PortfolioLedgerService().create_transaction(
        db, ticker=ticker, action="buy", quantity=Decimal("4"), price=Decimal("12.5"),
        trade_date=date(2025, 3, 3), fees=Decimal("0"), currency="USD",
    )
    db.commit()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    assert company is not None
    return company


def test_sin_cotizacion_no_hay_precio_del_modelo(db: Session):
    company = _buy(db, "ZZVMQ")
    assert resolve_model_price(db, company.id) is None


def test_mark_de_broker_sigue_siendo_precio(db: Session):
    company = _buy(db, "ZZVMB")
    position = db.scalar(select(Position).where(Position.company_id == company.id))
    assert position is not None
    position.source = "ibkr_flex"
    position.market_price = Decimal("11")
    db.commit()
    price = resolve_model_price(db, company.id)
    assert price is not None and price.value == 11.0
