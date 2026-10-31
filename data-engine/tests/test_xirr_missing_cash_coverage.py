"""XIRR perspectiva cuenta: sin saldo de caja no se publica cifra sesgada."""
from datetime import timedelta
from decimal import Decimal

import pytest
from scipy.optimize import brentq
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models.entities import Base, CashBalance, Company, Portfolio, Position, Transaction
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-probe"
        session.add(Portfolio(name="Main", base_currency="USD", is_default=True))
        session.commit()
        yield session


def _company(db, ticker="AAPL", currency="USD"):
    c = Company(ticker=ticker, name=ticker, exchange="NASDAQ", currency=currency,
                sector="T", industry="T", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
    db.add(c); db.commit(); return c


def _tx(db, company, action, qty, price, day, fees="0", currency="USD", payload=None):
    t = Transaction(company_id=company.id, trade_date=day, action=action,
                    quantity=Decimal(qty), price=Decimal(price), fees=Decimal(fees),
                    currency=currency, raw_payload=payload or {})
    db.add(t); db.commit(); return t


def _position(db, company, mv_base, currency="USD"):
    p = Position(company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("100"),
                 market_price=Decimal("110"), market_value=Decimal(mv_base),
                 unrealized_pnl=Decimal("0"), realized_pnl=Decimal("0"), currency=currency,
                 base_currency="USD", market_value_native=Decimal(mv_base),
                 market_value_base=Decimal(mv_base), as_of=local_today(), source="probe")
    db.add(p); db.commit(); return p


def _ref_xirr(flows):
    origin = min(d for d, _ in flows)
    def npv(r):
        return sum(v / ((1 + r) ** ((d - origin).days / 365.0)) for d, v in flows)
    return brentq(npv, -0.9999, 10.0)


def test_xirr_account_perspective_missing_cash_is_not_published(db):
    today = local_today()
    c = _company(db)
    _tx(db, c, "deposit", "1000", "1", today - timedelta(days=365))
    _tx(db, c, "buy", "5", "100", today - timedelta(days=364))
    p = _position(db, c, "550")
    xirr, trace = PortfolioIntelligenceService()._xirr(db, [(p, c)])
    # Antes: -45 % "calculated" (con la caja real de 500 serian +5 %).
    assert xirr is None
    assert trace["status"] == "incomplete_missing_cash_balance"
    assert trace["perspective"] == "account"


def test_xirr_account_perspective_with_cash_still_calculated(db):
    today = local_today()
    c = _company(db)
    _tx(db, c, "deposit", "1000", "1", today - timedelta(days=365))
    _tx(db, c, "buy", "5", "100", today - timedelta(days=364))
    p = _position(db, c, "550")
    db.add(CashBalance(currency="USD", balance=Decimal("500"), settled_cash=Decimal("500"),
                       as_of=today, source="probe"))
    db.commit()
    xirr, trace = PortfolioIntelligenceService()._xirr(db, [(p, c)])
    assert trace["status"] == "calculated"
    ref = _ref_xirr([(today - timedelta(days=365), -1000.0), (today, 1050.0)])
    assert xirr == pytest.approx(ref, abs=1e-6)
    assert xirr == pytest.approx(0.05, abs=0.001)


def test_xirr_investment_perspective_without_deposits_unaffected(db):
    today = local_today()
    c = _company(db)
    _tx(db, c, "buy", "10", "100", today - timedelta(days=365))
    p = _position(db, c, "1100")
    xirr, trace = PortfolioIntelligenceService()._xirr(db, [(p, c)])
    assert trace["perspective"] == "investment"
    assert trace["status"] == "calculated"
    assert xirr == pytest.approx(0.10, abs=0.001)
