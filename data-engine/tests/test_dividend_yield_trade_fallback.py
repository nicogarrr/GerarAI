"""Rentabilidad por dividendo: sin cotización real no se calcula sobre tu precio de compra.

``portfolio_yields`` dividía el dividendo de 12 meses entre ``Position.market_price``.
En una posición del ledger sin cotización ese «precio» es el de tu última
operación (auditoría A3, «sin cotización real» en /positions): la tabla de
dividendos enseñaba como rentabilidad actual lo que en realidad es la
rentabilidad sobre lo que pagaste, y además entraba en la media de la cartera.
Un mark de broker (IBKR) sigue valiendo.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, Position
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.portfolio_ledger_service import PortfolioLedgerService


class _NoProvider:
    async def dividends(self, ticker: str):  # pragma: no cover - never called
        return []


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _buy_with_dividend(db: Session, ticker: str) -> Company:
    PortfolioLedgerService().create_transaction(
        db, ticker=ticker, action="buy", quantity=Decimal("4"), price=Decimal("12.5"),
        trade_date=date(2025, 3, 3), fees=Decimal("0"), currency="USD",
    )
    db.commit()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    assert company is not None
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date.today() - timedelta(days=30),
            amount=Decimal("0.5"),
            currency="USD",
            source="fmp",
        )
    )
    db.commit()
    return company


def _row(db: Session, ticker: str) -> dict:
    result = DividendIngestionService(fmp=_NoProvider(), yahoo=_NoProvider()).portfolio_yields(db)
    return {row["ticker"]: row for row in result["positions"]}[ticker]


def test_sin_cotizacion_no_hay_rentabilidad_sobre_tu_precio(db: Session):
    _buy_with_dividend(db, "ZZDYQ")
    row = _row(db, "ZZDYQ")
    # El dividendo de 12 meses es un dato real y se sigue enseñando.
    assert row["ttm_dividend_per_share"] == pytest.approx(0.5)
    # 0,5 / 12,5 = 4 % era la rentabilidad sobre tu compra, no la de mercado.
    assert row["dividend_yield"] is None
    assert row["price"] is None


def test_mark_de_broker_sigue_dando_rentabilidad(db: Session):
    company = _buy_with_dividend(db, "ZZDYB")
    position = db.scalar(select(Position).where(Position.company_id == company.id))
    assert position is not None
    position.source = "ibkr_flex"
    position.market_price = Decimal("10")
    db.commit()
    row = _row(db, "ZZDYB")
    assert row["dividend_yield"] == pytest.approx(0.05)
    assert row["price"] == pytest.approx(10.0)
