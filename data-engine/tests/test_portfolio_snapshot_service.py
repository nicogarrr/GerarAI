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
    FxConversion,
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


def test_cash_dated_before_the_day_is_carried_forward_when_nothing_moved_it(db):
    """Flex dates cash at its last close; a same-day snapshot must still count it."""
    company = _company(db)
    _portfolio_positions(db, company, as_of=TODAY)
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=YESTERDAY))
    db.commit()

    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)

    assert snapshot.cash_value_base == Decimal("500")
    assert snapshot.total_value_base == Decimal("1500")
    assert snapshot.pricing_coverage == Decimal("1")
    assert snapshot.metadata_["missing_pricing"] == []
    assert snapshot.metadata_["cash_carried_forward"] == [
        {"cash_currency": "EUR", "valuation_date": YESTERDAY.isoformat()}
    ]


def test_cash_is_not_carried_forward_across_a_later_transaction(db):
    company = _company(db)
    portfolio, _ = _portfolio_positions(db, company, as_of=TODAY)
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=YESTERDAY))
    db.add(
        Transaction(
            portfolio_id=portfolio.id, trade_date=TODAY, action="buy",
            quantity=Decimal("1"), price=Decimal("10"), currency="EUR",
            external_id="buy-1",
        )
    )
    db.commit()

    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)

    assert snapshot.cash_value_base == Decimal("0")
    assert snapshot.pricing_coverage < Decimal("1")
    assert snapshot.metadata_["cash_carried_forward"] == []
    assert snapshot.daily_return is None


def test_cash_is_not_carried_forward_across_a_trade_in_another_portfolio(db):
    """La caja es de CUENTA (CashBalance no tiene portfolio_id) y el servicio
    la arrastra solo si "no hay ninguna operacion posterior al saldo". Una
    compra en OTRA cartera mueve esa misma caja: no puede pasar el filtro por
    cartera de la foto."""
    company = _company(db)
    _portfolio_positions(db, company, as_of=TODAY)  # cartera por defecto
    from app.models.entities import Portfolio

    other = Portfolio(name="Second", base_currency="EUR", is_default=False)
    db.add(other)
    db.commit()
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=YESTERDAY))
    db.add(
        Transaction(
            portfolio_id=other.id, trade_date=TODAY, action="buy",
            quantity=Decimal("1"), price=Decimal("10"), currency="EUR",
            external_id="buy-other-portfolio",
        )
    )
    db.commit()

    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)

    assert snapshot.cash_value_base == Decimal("0")
    assert snapshot.pricing_coverage < Decimal("1")
    assert snapshot.metadata_["cash_carried_forward"] == []
    assert snapshot.daily_return is None


def test_future_dated_cash_is_never_used_for_an_earlier_day(db):
    company = _company(db)
    _portfolio_positions(db, company, as_of=YESTERDAY)
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=TODAY))
    db.commit()

    snapshot = PortfolioSnapshotService().capture(db, as_of=YESTERDAY)

    assert snapshot.cash_value_base == Decimal("0")
    assert snapshot.metadata_["cash_carried_forward"] == []


def test_series_restarts_after_unvaluable_stretch_without_stitching(db):
    """Broken days stay null; the first complete day becomes the new base.

    d0, d1: positions stale => coverage < 1, no returns (the real 35-snapshot case).
    d2: complete, no return (previous unusable) -> new base.
    d3: complete, return chains from d2 only.
    """
    company = _company(db)
    portfolio, position = _portfolio_positions(db, company, as_of=TODAY - timedelta(days=9))
    service = PortfolioSnapshotService()
    d = [TODAY - timedelta(days=n) for n in (3, 2, 1, 0)]
    service.capture(db, as_of=d[0])  # position as_of far in the past: stale
    service.capture(db, as_of=d[1])
    position.as_of = d[2]
    db.commit()
    s2 = service.capture(db, as_of=d[2])
    position.as_of = d[3]
    position.market_price = Decimal("110")
    db.commit()
    s3 = service.capture(db, as_of=d[3])

    rows = db.scalars(
        select(PortfolioDailySnapshot).order_by(PortfolioDailySnapshot.snapshot_date)
    ).all()
    assert [r.daily_return for r in rows[:3]] == [None, None, None]
    assert s2.pricing_coverage == Decimal("1")
    assert s3.daily_return == pytest.approx(Decimal("0.1"))
    assert s3.cumulative_twr == pytest.approx(Decimal("0.1"))


def test_cash_is_not_carried_forward_across_an_fx_conversion(db):
    company = _company(db)
    _portfolio_positions(db, company, as_of=TODAY)
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=YESTERDAY))
    db.add(FxConversion(
        trade_date=TODAY, disposed_currency="EUR", disposed_amount=Decimal("100"),
        acquired_currency="USD", acquired_amount=Decimal("110"), external_id="fx-later",
    ))
    db.commit()
    snapshot = PortfolioSnapshotService().capture(db, as_of=TODAY)
    assert snapshot.cash_value_base == Decimal("0")
    assert snapshot.pricing_coverage < Decimal("1")
    assert snapshot.metadata_["cash_carried_forward"] == []
