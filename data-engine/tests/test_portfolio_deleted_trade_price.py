"""Sin cotización, la posición no se queda valorada al precio de una operación
que ya no existe (borrada) o que ha cambiado (editada).

Sin cotización guardada, rebuild_position valora con el precio de la última
operación (respaldo A3). Con compras a 10 € y 14 €, la posición queda a 14 €;
al BORRAR la de 14 € la posición seguía a 14 € (ya no es el precio de ninguna
operación, así que pasaba por cotización real) y enseñaba +40 € de plusvalía
inventada sobre 10 títulos comprados a 10 €. Igual al editar el precio.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.portfolio import PortfolioTransactionInput, delete_transaction, update_transaction
from app.models.entities import Base, MarketPrice, Position, Transaction
from app.services.portfolio_ledger_service import PortfolioLedgerService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _buy(service, db, price, day):
    return service.create_transaction(
        db, ticker="AAPL", action="buy", quantity=Decimal("10"), price=Decimal(price),
        trade_date=day, currency="EUR",
    )


def _position(db) -> Position:
    position = db.scalar(select(Position))
    assert position is not None
    return position


def test_deleting_last_trade_does_not_keep_its_price_as_quote(db):
    service = PortfolioLedgerService()
    _buy(service, db, "10", date(2026, 1, 10))
    second = _buy(service, db, "14", date(2026, 2, 10))
    db.commit()
    assert _position(db).market_price == Decimal("14")

    delete_transaction(second.id, db)

    position = _position(db)
    assert position.quantity == Decimal("10")
    assert position.market_price == Decimal("10")
    assert position.unrealized_pnl == Decimal("0")


def test_editing_trade_price_does_not_keep_old_price_as_quote(db):
    service = PortfolioLedgerService()
    only = _buy(service, db, "10", date(2026, 1, 10))
    db.commit()

    update_transaction(
        only.id,
        PortfolioTransactionInput(
            ticker="AAPL", action="buy", quantity=Decimal("10"), price=Decimal("12"),
            trade_date=date(2026, 1, 10), currency="EUR",
        ),
        db,
    )

    position = _position(db)
    assert position.market_price == Decimal("12")
    assert position.unrealized_pnl == Decimal("0")


def test_real_quote_survives_deleting_a_trade_with_the_same_price(db):
    service = PortfolioLedgerService()
    first = _buy(service, db, "10", date(2026, 1, 10))
    second = _buy(service, db, "14", date(2026, 2, 10))
    company_id = second.company_id
    # Cotización real posterior que casualmente vale 14: no es un respaldo.
    db.add(MarketPrice(company_id=company_id, date=date(2026, 3, 1), close=Decimal("14"), source="test"))
    service.update_market_price(db, company_id=company_id, price=Decimal("14"), as_of=date(2026, 3, 1))
    db.commit()

    delete_transaction(second.id, db)

    position = _position(db)
    assert position.market_price == Decimal("14")
    assert db.get(Transaction, first.id) is not None
