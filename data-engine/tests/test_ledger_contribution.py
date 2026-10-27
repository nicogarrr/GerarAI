"""Ledger-contribution attribution tests."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CashBalance,
    Company,
    MarketPrice,
    Portfolio,
    Position,
    Transaction,
)
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService

CUTOFF = date(2026, 1, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "AAA") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _position(db: Session, company: Company, qty: float, price: float) -> Position:
    portfolio = Portfolio(name="p", base_currency="USD")
    db.add(portfolio)
    db.commit()
    position = Position(
        portfolio_id=portfolio.id, company_id=company.id, quantity=Decimal(str(qty)),
        average_cost=Decimal("100"), market_price=Decimal(str(price)),
        market_value=Decimal(str(qty * price)), unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"), as_of=date.today(), currency="USD",
        base_currency="USD", market_value_base=Decimal(str(qty * price)),
    )
    db.add(position)
    db.commit()
    return position


def _tx(db: Session, company: Company, action: str, qty: float, price: float, day: date, fees: float = 0.0) -> None:
    db.add(Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)), fees=Decimal(str(fees)),
        currency="USD", raw_payload={},
    ))
    db.commit()


def _price(db: Session, company: Company, day: date, close: float) -> None:
    db.add(MarketPrice(
        company_id=company.id, date=day, open=Decimal(str(close)), high=Decimal(str(close)),
        low=Decimal(str(close)), close=Decimal(str(close)), adj_close=Decimal(str(close)),
        volume=1, source="test",
    ))
    db.commit()


def _usd_base(db: Session) -> None:
    db.add(CashBalance(currency="USD", balance=Decimal("0")))
    db.commit()


def test_buy_and_hold_contribution(db):
    _usd_base(db)
    company = _company(db)
    position = _position(db, company, qty=10, price=150)  # end value 1500
    # Bought before the horizon at 100; price before cutoff was 120.
    _tx(db, company, "buy", 10, 100, date(2025, 6, 1))
    _price(db, company, CUTOFF - timedelta(days=1), 120)
    result = PortfolioIntelligenceService()._ledger_contribution(
        db, [(position, company)], CUTOFF
    )
    entry = result["positions"][0]
    # start value = 10 * 120 = 1200; end = 1500; no flows in horizon.
    assert entry["start_value"] == pytest.approx(1200.0)
    assert entry["contribution_pnl"] == pytest.approx(300.0)
    assert entry["contribution_share"] == pytest.approx(1.0)
    assert result["total_pnl"] == pytest.approx(300.0)


def test_flows_and_income_inside_horizon(db):
    _usd_base(db)
    company = _company(db)
    # La cantidad actual debe reconciliar con los legs: 10 + 5 - 5 = 10.
    position = _position(db, company, qty=10, price=100)  # end 1000
    _tx(db, company, "buy", 10, 100, date(2025, 6, 1))  # pre-horizon
    _price(db, company, CUTOFF - timedelta(days=1), 100)  # start = 1000
    _tx(db, company, "buy", 5, 80, CUTOFF + timedelta(days=10))  # invested 400
    _tx(db, company, "sell", 5, 110, CUTOFF + timedelta(days=20))  # proceeds 550
    _tx(db, company, "dividend", 1, 25, CUTOFF + timedelta(days=30))  # income 25
    result = PortfolioIntelligenceService()._ledger_contribution(
        db, [(position, company)], CUTOFF
    )
    entry = result["positions"][0]
    # pnl = 1000 - 1000 - 400 + 550 + 25 = 175
    assert entry["contribution_pnl"] == pytest.approx(175.0)
    assert entry["net_invested"] == pytest.approx(400 - 550)
    assert entry["income"] == pytest.approx(25.0)


def test_missing_start_price_is_honest_null(db):
    _usd_base(db)
    company = _company(db)
    position = _position(db, company, qty=10, price=150)
    _tx(db, company, "buy", 10, 100, date(2025, 6, 1))
    # No price rows at all.
    result = PortfolioIntelligenceService()._ledger_contribution(
        db, [(position, company)], CUTOFF
    )
    entry = result["positions"][0]
    assert entry["contribution_pnl"] is None
    assert entry["reason"] == "missing_start_price"
    assert result["coverage"]["reasons"] == {"missing_start_price": 1}
    assert result["total_pnl"] is None


def test_position_opened_inside_horizon_needs_no_start_price(db):
    _usd_base(db)
    company = _company(db)
    position = _position(db, company, qty=5, price=110)  # end 550
    _tx(db, company, "buy", 5, 100, CUTOFF + timedelta(days=5))  # invested 500
    result = PortfolioIntelligenceService()._ledger_contribution(
        db, [(position, company)], CUTOFF
    )
    entry = result["positions"][0]
    assert entry["start_value"] == 0.0
    assert entry["contribution_pnl"] == pytest.approx(50.0)


def test_multi_position_shares_sum_to_one(db):
    _usd_base(db)
    aaa = _company(db, "AAA")
    bbb = _company(db, "BBB")
    pos_a = _position(db, aaa, qty=10, price=150)
    pos_b = _position(db, bbb, qty=10, price=90)
    _tx(db, aaa, "buy", 10, 100, date(2025, 6, 1))
    _tx(db, bbb, "buy", 10, 100, date(2025, 6, 1))
    _price(db, aaa, CUTOFF - timedelta(days=1), 120)
    _price(db, bbb, CUTOFF - timedelta(days=1), 100)
    result = PortfolioIntelligenceService()._ledger_contribution(
        db, [(pos_a, aaa), (pos_b, bbb)], CUTOFF
    )
    # AAA: 1500-1200=+300; BBB: 900-1000=-100; total=200.
    assert result["total_pnl"] == pytest.approx(200.0)
    shares = [p["contribution_share"] for p in result["positions"]]
    assert shares[0] == pytest.approx(1.5)  # signed share: winner > 100%
    assert shares[1] == pytest.approx(-0.5)
    assert sum(shares) == pytest.approx(1.0)


def test_position_without_ledger_is_honest_null(db):
    """Sin transacciones no hay reconstrucción: P&L = valor íntegro es mentira."""
    company = _company(db, "NOLEDGER")
    _position(db, company, qty=10, price=1770.20)
    result = PortfolioIntelligenceService()._ledger_contribution(db, [(db.query(Position).one(), company)], CUTOFF)
    assert result["positions"][0]["contribution_pnl"] is None
    assert result["positions"][0]["reason"] == "missing_ledger"
    assert result["total_pnl"] is None
    assert result["coverage"]["with_contribution"] == 0
    assert result["coverage"]["reasons"] == {"missing_ledger": 1}


def test_dividend_only_ledger_is_honest_null(db):
    """Un dividendo suelto no reconstruye la posición: P&L inventada si no."""
    company = _company(db, "DIVONLY")
    _position(db, company, qty=10, price=1770.20)
    _tx(db, company, "dividend", 10, 0.5, date(2026, 2, 1))
    position = db.query(Position).one()
    result = PortfolioIntelligenceService()._ledger_contribution(db, [(position, company)], CUTOFF)
    assert result["positions"][0]["contribution_pnl"] is None
    assert result["positions"][0]["reason"] == "missing_ledger"
    assert result["total_pnl"] is None


def test_partial_ledger_is_honest_null(db):
    """Compra de 1 acción sobre posición de 10: ledger incompleto, nulo."""
    company = _company(db, "PARTIAL")
    _position(db, company, qty=10, price=100)
    _tx(db, company, "buy", 1, 90, date(2025, 6, 1))
    position = db.query(Position).one()
    result = PortfolioIntelligenceService()._ledger_contribution(db, [(position, company)], CUTOFF)
    assert result["positions"][0]["contribution_pnl"] is None
    assert result["positions"][0]["reason"] == "incomplete_ledger"
    assert result["total_pnl"] is None
    assert result["coverage"]["reasons"] == {"incomplete_ledger": 1}


def test_missing_end_value_in_base_is_honest_null_not_total_loss(db):
    """Sin market_value_base (falta el FX de hoy) el valor final es
    desconocido, no 0: antes la contribucion salia como una perdida del 100 %
    (0 - 1200 = -1200) y entraba en el total."""
    _usd_base(db)
    company = _company(db)
    position = _position(db, company, qty=10, price=150)
    position.market_value_base = None
    db.commit()
    _tx(db, company, "buy", 10, 100, date(2025, 6, 1))
    _price(db, company, CUTOFF - timedelta(days=1), 120)
    result = PortfolioIntelligenceService()._ledger_contribution(
        db, [(position, company)], CUTOFF
    )
    entry = result["positions"][0]
    assert entry["contribution_pnl"] is None
    assert entry["end_value"] is None
    assert entry["reason"] == "missing_end_value"
    assert result["total_pnl"] is None
