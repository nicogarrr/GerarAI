"""A split rescales share-denominated legs ONLY.

Cash movements (dividend, withholding, interest, fee, cash_misc) store a money
AMOUNT in ``price`` with ``quantity`` 0 or 1 - the shape
``PortfolioLedgerService`` documents and the IBKR importer writes
(``quantity=1, price=amount``). The split rewrite used to iterate EVERY
transaction before the effective date and divide whatever it found in
``price``, so a 4:1 split turned a EUR 100 dividend into EUR 25 and a EUR 9.95
commission into EUR 2.49, and ``tax_report_service`` declared the divided
figure on the fiscal return. buy/sell legs must still be rescaled.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position, Transaction
from app.services.corporate_actions_service import CorporateActionService

EFFECTIVE = date(2026, 6, 1)
RATIO = Decimal("4")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str = "SPL") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _tx(db: Session, company: Company, day: date, action: str, qty, price) -> Transaction:
    row = Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)),
        fees=Decimal("0"), currency="USD",
    )
    db.add(row)
    db.commit()
    return row


def test_split_leaves_cash_amounts_untouched(db: Session):
    company = _company(db)
    # Canonical cash shape: amount in price, quantity 0 or 1.
    dividend = _tx(db, company, date(2026, 4, 1), "dividend", 0, 100)
    withholding = _tx(db, company, date(2026, 4, 1), "withholding", 1, 19)
    commission = _tx(db, company, date(2026, 4, 2), "fee", 1, "9.95")
    interest = _tx(db, company, date(2026, 4, 3), "interest", 0, "3.50")
    misc = _tx(db, company, date(2026, 4, 4), "cash_misc", 0, "1.25")

    CorporateActionService().create_action(
        db, ticker="SPL", action_type="split",
        effective_date=EFFECTIVE, ratio=RATIO,
    )

    for row, amount in (
        (dividend, "100"), (withholding, "19"), (commission, "9.95"),
        (interest, "3.50"), (misc, "1.25"),
    ):
        db.refresh(row)
        assert Decimal(row.price) == Decimal(amount), row.action
        assert Decimal(row.quantity) in (Decimal("0"), Decimal("1")), row.action


def test_split_still_rescales_buy_and_sell_legs(db: Session):
    company = _company(db)
    buy = _tx(db, company, date(2026, 1, 10), "buy", 10, 100)
    sell = _tx(db, company, date(2026, 2, 10), "sell", 4, 150)
    dividend = _tx(db, company, date(2026, 3, 1), "dividend", 1, 25)
    after = _tx(db, company, date(2026, 7, 1), "buy", 2, 40)

    CorporateActionService().create_action(
        db, ticker="SPL", action_type="split",
        effective_date=EFFECTIVE, ratio=RATIO,
    )

    db.refresh(buy)
    assert buy.quantity == Decimal("40")
    assert buy.price == Decimal("25")
    assert buy.quantity * buy.price == Decimal("1000")
    db.refresh(sell)
    assert sell.quantity == Decimal("16")
    assert sell.price == Decimal("37.50")
    # Cash leg in the same company, same window: untouched.
    db.refresh(dividend)
    assert dividend.price == Decimal("25")
    # Leg already post-split: untouched.
    db.refresh(after)
    assert after.quantity == Decimal("2") and after.price == Decimal("40")


def test_split_rejects_manual_position_money_columns_untouched(db: Session):
    """Posicion manual sin libro: se rechaza y no se escribe nada."""
    company = _company(db)
    position = Position(
        company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("100"),
        market_price=Decimal("150"), market_value=Decimal("1500"),
        currency="USD", base_currency="USD", cost_basis_native=Decimal("1000"),
        as_of=date(2026, 5, 1),
    )
    db.add(position)
    db.commit()
    with pytest.raises(ValueError, match="Split rejected"):
        CorporateActionService().create_action(
            db, ticker="SPL", action_type="split",
            effective_date=EFFECTIVE, ratio=RATIO,
        )
    db.rollback()
    db.refresh(position)
    assert position.quantity == Decimal("10")
    assert position.market_value == Decimal("1500")
    assert position.as_of == date(2026, 5, 1)
