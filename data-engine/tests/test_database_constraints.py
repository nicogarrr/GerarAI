"""Pruebas de verificacion de restricciones de base de datos (NOT NULL, UNIQUE, CHECK).

Fulfills: VAL-DB-003, VAL-DB-008
Expected Behavior:
- All required fields have NOT NULL constraints
- Unique constraints on tenant, portfolio name, and transactions
- CHECK constraints on positive quantities, prices, and fees
- Constraint violations raise IntegrityError and prevent corrupt data
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, MarketPrice, Portfolio, Position, Tenant, Transaction


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_cls = sessionmaker(bind=engine)
    session = session_cls()
    session.info["tenant_id"] = 1
    try:
        yield session
    finally:
        session.close()


def test_not_null_constraints_company(db):
    """Verifica que los campos obligatorios de Company fallen si son NULL."""
    # Falta exchange (NOT NULL)
    c1 = Company(
        ticker="TEST1",
        name="Test 1",
        exchange=None,  # type: ignore
        currency="EUR",
        company_type="operating",
        valuation_model="standard",
    )
    db.add(c1)
    with pytest.raises(IntegrityError, match="NOT NULL"):
        db.commit()
    db.rollback()


def test_unique_constraint_portfolio_name_per_tenant(db):
    """Verifica que no se puedan crear dos carteras con el mismo nombre para un tenant."""
    p1 = Portfolio(name="Principal", base_currency="EUR", is_default=True, tenant_id=1)
    db.add(p1)
    db.commit()

    p2 = Portfolio(name="Principal", base_currency="EUR", is_default=False, tenant_id=1)
    db.add(p2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_constraint_tenant_external_id(db):
    """Verifica la unicidad de external_id en tenants."""
    t1 = Tenant(external_id="empresa-a", name="A")
    db.add(t1)
    db.commit()

    t2 = Tenant(external_id="empresa-a", name="A duplicada")
    db.add(t2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_check_constraint_transaction_quantity_non_negative(db):
    """Verifica que transactions rechace cantidades negativas via CHECK constraint."""
    p = Portfolio(name="Main", base_currency="EUR", tenant_id=1)
    c = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", company_type="operating", valuation_model="standard")
    db.add_all([p, c])
    db.commit()

    # Cantidad negativa (-10)
    tx = Transaction(
        portfolio_id=p.id,
        company_id=c.id,
        trade_date=date(2026, 3, 1),
        action="buy",
        quantity=Decimal("-10.0"),
        price=Decimal("150.0"),
        fees=Decimal("1.0"),
        tenant_id=1,
    )
    db.add(tx)
    with pytest.raises(IntegrityError, match="CHECK constraint failed: ck_transactions_quantity_non_negative"):
        db.commit()
    db.rollback()


def test_check_constraint_transaction_price_non_negative(db):
    """Verifica que transactions rechace precios negativos via CHECK constraint."""
    p = Portfolio(name="Main", base_currency="EUR", tenant_id=1)
    c = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", company_type="operating", valuation_model="standard")
    db.add_all([p, c])
    db.commit()

    # Precio negativo (-5.0)
    tx = Transaction(
        portfolio_id=p.id,
        company_id=c.id,
        trade_date=date(2026, 3, 1),
        action="buy",
        quantity=Decimal("10.0"),
        price=Decimal("-5.0"),
        fees=Decimal("1.0"),
        tenant_id=1,
    )
    db.add(tx)
    with pytest.raises(IntegrityError, match="CHECK constraint failed: ck_transactions_price_non_negative"):
        db.commit()
    db.rollback()


def test_check_constraint_market_price_close_non_negative(db):
    """Verifica que market_prices rechace precios de cierre negativos."""
    c = Company(ticker="NVDA", name="NVIDIA", exchange="NASDAQ", currency="USD", company_type="operating", valuation_model="standard")
    db.add(c)
    db.commit()

    mp = MarketPrice(
        company_id=c.id,
        date=date(2026, 3, 1),
        close=Decimal("-100.0"),
    )
    db.add(mp)
    with pytest.raises(IntegrityError, match="CHECK constraint failed: ck_market_prices_close_non_negative"):
        db.commit()
    db.rollback()


def test_valid_entities_pass_all_constraints(db):
    """Verifica que entidades con valores validos cumplan todas las restricciones."""
    p = Portfolio(name="Inversiones Europa", base_currency="EUR", tenant_id=1)
    c = Company(ticker="ASML", name="ASML Holding", exchange="AMS", currency="EUR", company_type="operating", valuation_model="standard")
    db.add_all([p, c])
    db.commit()

    tx = Transaction(
        portfolio_id=p.id,
        company_id=c.id,
        trade_date=date(2026, 3, 1),
        action="buy",
        quantity=Decimal("5.0"),
        price=Decimal("700.0"),
        fees=Decimal("2.5"),
        currency="EUR",
        tenant_id=1,
    )
    pos = Position(
        portfolio_id=p.id,
        company_id=c.id,
        quantity=Decimal("5.0"),
        market_price=Decimal("720.0"),
        tenant_id=1,
    )
    mp = MarketPrice(
        company_id=c.id,
        date=date(2026, 3, 1),
        open=Decimal("695.0"),
        high=Decimal("725.0"),
        low=Decimal("690.0"),
        close=Decimal("720.0"),
    )
    db.add_all([tx, pos, mp])
    db.commit()

    assert tx.id is not None
    assert pos.id is not None
    assert mp.id is not None

