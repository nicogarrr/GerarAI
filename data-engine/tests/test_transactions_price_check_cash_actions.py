"""ck_transactions_price_non_negative solo vela por las patas buy/sell.

VAL-DB-003 (migracion 0108) exigio ``price >= 0`` para TODA transaccion, pero
IBKR Flex entrega la retencion ('Withholding Tax') y 'Other Fees' como
CashTransactions con importe NEGATIVO (salida de dinero) y el importador
guarda el signo porque el XIRR lo usa para clasificar flujos. Resultado: cada
retencion real reventaba el import con IntegrityError. La restriccion queda
ahora limitada a buy/sell; las acciones de caja conservan el signo.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Transaction
from app.services.portfolio_fx_service import PortfolioFXService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture
def book(db):
    company = Company(
        ticker="WHT", name="Withheld Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    portfolio = PortfolioFXService().ensure_portfolio(db)
    return portfolio, company


def _tx(portfolio, company, action, price):
    return Transaction(
        portfolio_id=portfolio.id, company_id=company.id,
        trade_date=date(2026, 5, 3), action=action, quantity=Decimal("1"),
        price=Decimal(price), currency="EUR",
    )


@pytest.mark.parametrize("action", ["withholding", "fee", "interest", "cash_misc", "dividend"])
def test_cash_actions_aceptan_importe_negativo(db, book, action):
    portfolio, company = book
    db.add(_tx(portfolio, company, action, "-15"))
    db.commit()  # no IntegrityError: el signo es la direccion del flujo


@pytest.mark.parametrize("action", ["buy", "sell"])
def test_patas_de_compraventa_rechazan_precio_negativo(db, book, action):
    portfolio, company = book
    db.add(_tx(portfolio, company, action, "-15"))
    with pytest.raises(IntegrityError):
        db.commit()
