"""PortfolioSnapshotService contract tests.

Daily snapshots drive performance charts: values must be FX-converted
point-in-time, stale or unpriced rows excluded and reported, recapture
idempotent, and TWR computed only when the data supports it honestly.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CashBalance,
    CashDailySnapshot,
    Company,
    PortfolioDailySnapshot,
    Position,
    PositionDailySnapshot,
    Transaction,
)
from app.services.portfolio_snapshot_service import PortfolioSnapshotService

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _portfolio_positions(db: Session, company: Company, *, as_of: date):
    """Positions attach to the default portfolio the service ensures."""
    from app.services.portfolio_fx_service import PortfolioFXService

    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.commit()
    position = Position(
        portfolio_id=portfolio.id, company_id=company.id,
        quantity=Decimal("10"), market_price=Decimal("100"),
        currency="EUR", as_of=as_of,
    )
    db.add(position)
    db.commit()
    return portfolio, position


def test_capture_values_at_par_and_writes_child_rows(db):
    company = _company(db)
    _portfolio_positions(db, company, as_of=TODAY)
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=TODAY))
    db.commit()

    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snapshot.positions_value_base == Decimal("1000")
    assert snapshot.cash_value_base == Decimal("500")
    assert snapshot.total_value_base == Decimal("1500")
    assert snapshot.pricing_coverage == Decimal("1")
    assert snapshot.metadata_["missing_pricing"] == []
    rows = db.scalars(select(PositionDailySnapshot)).all()
    assert len(rows) == 1
    assert rows[0].weight == pytest.approx(Decimal("1000") / Decimal("1500"))
    assert db.scalars(select(CashDailySnapshot)).all()[0].balance_base == Decimal("500")


def test_stale_or_unpriced_rows_excluded_and_reported(db):
    company = _company(db)
    # Position priced yesterday, not today: stale for today's snapshot.
    _portfolio_positions(db, company, as_of=YESTERDAY)
    db.add(CashBalance(currency="USD", balance=Decimal("800"), as_of=TODAY))  # no USD rate
    db.commit()

    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snapshot.total_value_base == Decimal("0")
    assert len(snapshot.metadata_["missing_pricing"]) == 2
    assert snapshot.pricing_coverage == Decimal("0")
    # No full-coverage honest data: no return is fabricated.
    assert snapshot.daily_return is None


def test_recapture_same_day_replaces_child_rows(db):
    company = _company(db)
    _, position = _portfolio_positions(db, company, as_of=TODAY)
    service = PortfolioSnapshotService()
    service.capture(db, as_of=TODAY)
    position.market_price = Decimal("120")
    db.commit()
    snapshot = service.capture(db, as_of=TODAY)

    assert db.scalar(select(func.count()).select_from(PortfolioDailySnapshot)) == 1
    assert db.scalar(select(func.count()).select_from(PositionDailySnapshot)) == 1
    assert snapshot.positions_value_base == Decimal("1200")


def test_twr_excludes_external_flows_and_requires_full_coverage(db):
    company = _company(db)
    portfolio, position = _portfolio_positions(db, company, as_of=YESTERDAY)
    service = PortfolioSnapshotService()
    service.capture(db, as_of=YESTERDAY)  # total 1000

    # Today: price doubles AND the user deposits 500 EUR.
    position.as_of = TODAY
    position.market_price = Decimal("200")
    db.add(
        Transaction(
            portfolio_id=portfolio.id, trade_date=TODAY, action="deposit",
            quantity=Decimal("1"), price=Decimal("500"), currency="EUR",
            external_id="dep-1",
        )
    )
    db.commit()
    snapshot = service.capture(db, as_of=TODAY)

    assert snapshot.net_external_flow_base == Decimal("500")
    # (2000 - 500) / 1000 - 1 = 0.5: the deposit never counts as performance.
    assert snapshot.daily_return == pytest.approx(Decimal("0.5"))
    assert snapshot.cumulative_twr == pytest.approx(Decimal("0.5"))


def test_ambiguous_flow_blocks_return_calculation(db):
    company = _company(db)
    portfolio, position = _portfolio_positions(db, company, as_of=YESTERDAY)
    service = PortfolioSnapshotService()
    service.capture(db, as_of=YESTERDAY)

    position.as_of = TODAY
    db.add(
        Transaction(
            portfolio_id=portfolio.id, trade_date=TODAY, action="cash_misc",
            quantity=Decimal("1"), price=Decimal("100"), currency="EUR",
            external_id="misc-1",
        )
    )
    db.commit()
    snapshot = service.capture(db, as_of=TODAY)
    assert snapshot.daily_return is None
    assert snapshot.metadata_["ambiguous_external_flows"]



def test_margin_weights_use_gross_positions_not_nav(db):
    """Auditoria A: posiciones 100, caja -25, NAV 75 -> el peso guardado era
    1.333 (133 %). Con margen se pesa sobre la exposicion bruta (1.0) y la
    caja negativa se conserva aparte con su signo."""
    company = _company(db)
    portfolio, position = _portfolio_positions(db, company, as_of=TODAY)
    position.quantity = Decimal("1")
    db.add(CashBalance(currency="EUR", balance=Decimal("-25"), as_of=TODAY))
    db.commit()

    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snapshot.positions_value_base == Decimal("100")
    assert snapshot.cash_value_base == Decimal("-25")
    assert snapshot.total_value_base == Decimal("75")
    rows = db.scalars(select(PositionDailySnapshot)).all()
    assert rows[0].weight == pytest.approx(Decimal("1"))
    assert snapshot.metadata_["weight_basis"] == "gross_positions"


def test_positive_cash_keeps_nav_weight_basis(db):
    company = _company(db)
    _portfolio_positions(db, company, as_of=TODAY)
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=TODAY))
    db.commit()
    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snapshot.metadata_["weight_basis"] == "total_with_cash"
