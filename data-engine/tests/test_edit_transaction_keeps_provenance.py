"""Editar una operación importada conserva su rastro de origen.

El PUT reescribía ``raw_payload`` entero con ``{"notes": ...}``: al añadir una
nota a una compra de IBKR se perdían tradeID/accountId/ibOrderID. La
conciliación de costes de IBKR pasaba a «non_native_trades» y la posición
enseñaba coste y plusvalía como N/D; la identidad del import CSV también se
perdía. Solo «notes» es del usuario; el resto del rastro se conserva.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.portfolio import PortfolioTransactionInput, update_transaction
from app.models.entities import Base, Transaction
from app.services.portfolio_ledger_service import PortfolioLedgerService

IBKR_PAYLOAD = {
    "tradeID": "487001",
    "accountId": "U1234567",
    "ibOrderID": "9001",
    "ibCommissionCurrency": "USD",
    "notes": "O",
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _imported_buy(db) -> Transaction:
    trade = PortfolioLedgerService().create_transaction(
        db, ticker="AAPL", action="buy", quantity=Decimal("10"), price=Decimal("150"),
        trade_date=date(2026, 1, 10), currency="USD",
    )
    trade.external_id = "487001"
    trade.raw_payload = dict(IBKR_PAYLOAD)
    db.commit()
    return trade


def _edit(db, trade_id: int, notes: str | None, price: str = "150") -> None:
    update_transaction(
        trade_id,
        PortfolioTransactionInput(
            ticker="AAPL", action="buy", quantity=Decimal("10"), price=Decimal(price),
            trade_date=date(2026, 1, 10), currency="USD", notes=notes,
        ),
        db,
    )


def test_adding_a_note_keeps_ibkr_provenance(db):
    trade = _imported_buy(db)

    _edit(db, trade.id, "revisar comisión")

    stored = db.get(Transaction, trade.id)
    assert stored is not None
    assert stored.raw_payload == {**IBKR_PAYLOAD, "notes": "revisar comisión"}
    assert stored.external_id == "487001"


def test_clearing_the_note_keeps_the_rest_of_the_payload(db):
    trade = _imported_buy(db)

    _edit(db, trade.id, None, price="151")

    stored = db.get(Transaction, trade.id)
    assert stored is not None
    expected = {k: v for k, v in IBKR_PAYLOAD.items() if k != "notes"}
    assert stored.raw_payload == expected
    assert stored.price == Decimal("151")


def test_manual_trade_still_stores_only_the_note(db):
    trade = PortfolioLedgerService().create_transaction(
        db, ticker="AAPL", action="buy", quantity=Decimal("10"), price=Decimal("150"),
        trade_date=date(2026, 1, 10), currency="USD",
    )
    db.commit()

    _edit(db, trade.id, "nota")
    assert db.get(Transaction, trade.id).raw_payload == {"notes": "nota"}  # type: ignore[union-attr]

    _edit(db, trade.id, None)
    assert db.get(Transaction, trade.id).raw_payload == {}  # type: ignore[union-attr]
