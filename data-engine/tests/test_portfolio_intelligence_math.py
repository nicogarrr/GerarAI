"""PortfolioIntelligenceService math contract tests.

Performance numbers the user reads must be exactly computable from the
stored series: returns, compounding, drawdown, VaR/CVaR and XIRR each
carry an honest "insufficient data" path instead of a plausible guess.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, Position, Transaction
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _prices(db: Session, company: Company, closes: list[tuple[date, str]]):
    for day, close in closes:
        db.add(
            MarketPrice(
                company_id=company.id, date=day, open=Decimal(close),
                high=Decimal(close), low=Decimal(close), close=Decimal(close),
                adj_close=Decimal(close), source="Finnhub",
            )
        )
    db.commit()


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_returns_from_adj_close_ratios(db):
    today = date.today()
    company = _company(db)
    _prices(db, company, [
        (today - timedelta(days=2), "100"),
        (today - timedelta(days=1), "110"),
        (today, "99"),
    ])
    service = PortfolioIntelligenceService()
    series = db.query(MarketPrice).order_by(MarketPrice.date).all()
    returns = service._returns(series)
    assert returns[today - timedelta(days=1)] == pytest.approx(0.10)
    assert returns[today] == pytest.approx(-0.10)


def test_portfolio_returns_renormalize_active_weights():
    returns = {
        1: {date(2026, 9, 22): 0.10, date(2026, 9, 23): 0.02},
        2: {date(2026, 9, 23): -0.04},
    }
    weights = {1: 0.75, 2: 0.25}
    result = PortfolioIntelligenceService._portfolio_returns(returns, weights)
    # Day 1: only company 1 traded -> its return stands alone.
    assert result[date(2026, 9, 22)] == pytest.approx(0.10)
    # Day 2: weighted average across both.
    assert result[date(2026, 9, 23)] == pytest.approx(0.75 * 0.02 + 0.25 * -0.04)


def test_compound_and_drawdown():
    service = PortfolioIntelligenceService()
    assert service._compound([0.10, -0.10]) == pytest.approx(-0.01)
    dd = service._drawdown({
        date(2026, 9, 21): 0.10,
        date(2026, 9, 22): -0.20,
        date(2026, 9, 23): 0.05,
    })
    # Peak after day 1 is 1.1; day 2 lands at 0.88 -> drawdown -0.2.
    assert dd["max_drawdown"] == pytest.approx(-0.20)
    assert len(dd["series"]) == 3
    assert service._drawdown({})["max_drawdown"] is None


def test_historical_var_requires_enough_observations():
    service = PortfolioIntelligenceService()
    few = {date(2026, 9, 1) + timedelta(days=i): -0.01 for i in range(19)}
    assert service._historical_var(few) == (None, None)
    many = {date(2026, 5, 1) + timedelta(days=i): (i - 50) / 1000 for i in range(100)}
    var, cvar = service._historical_var(many, confidence=0.95)
    assert var == pytest.approx(-0.045)  # 5th smallest of -0.050..0.049
    assert cvar == pytest.approx((-0.050 - 0.049 - 0.048 - 0.047 - 0.046 - 0.045) / 6)


def test_xirr_money_weighted_return(db, monkeypatch):
    today = date.today()

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return today

    import app.services.portfolio_intelligence_service as pi_module

    monkeypatch.setattr(pi_module, "date", _FixedDate)
    company = _company(db)
    service = PortfolioIntelligenceService()
    from app.services.portfolio_fx_service import PortfolioFXService

    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.add(
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id,
            trade_date=today - timedelta(days=365), action="buy",
            quantity=Decimal("10"), price=Decimal("100"), currency="EUR",
            external_id="xirr-1",
        )
    )
    position = Position(
        portfolio_id=portfolio.id, company_id=company.id,
        quantity=Decimal("10"), market_price=Decimal("110"),
        market_value_base=Decimal("1100"), currency="EUR", as_of=today,
    )
    db.add(position)
    db.commit()

    xirr, meta = service._xirr(db, [(position, company)])
    assert meta["status"] == "calculated"
    assert xirr == pytest.approx(0.10, abs=1e-4)


def test_xirr_honest_when_cashflows_insufficient(db):
    service = PortfolioIntelligenceService()
    xirr, meta = service._xirr(db, [])
    assert xirr is None
    assert meta["status"] == "insufficient_cashflows"


def test_snapshot_history_exactness_gate():
    service = PortfolioIntelligenceService()

    def snap(day, **overrides):
        base = {
            "snapshot_date": day, "daily_return": Decimal("0.01"),
            "pricing_coverage": Decimal("1"), "metadata_": {},
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    good = [snap(date(2026, 9, 21), daily_return=None), snap(date(2026, 9, 22)), snap(date(2026, 9, 23))]
    assert service._snapshot_history_is_exact(good) is True
    assert service._snapshot_history_is_exact([snap(date(2026, 9, 23))]) is False
    gap = [snap(date(2026, 9, 1)), snap(date(2026, 9, 23))]
    assert service._snapshot_history_is_exact(gap) is False
    missing_return = [snap(date(2026, 9, 22)), snap(date(2026, 9, 23), daily_return=None)]
    assert service._snapshot_history_is_exact(missing_return) is False
    ambiguous = [snap(date(2026, 9, 22)), snap(date(2026, 9, 23), metadata_={"ambiguous_external_flows": [1]})]
    assert service._snapshot_history_is_exact(ambiguous) is False


def test_attribution_facts_are_limited_to_the_price_window():
    from types import SimpleNamespace

    from app.services.portfolio_intelligence_service import PortfolioIntelligenceService as S

    def fact(year, value):
        return SimpleNamespace(fiscal_year=year, fiscal_quarter=None, value=value)

    shares = [fact(2019, 100), fact(2021, 150), fact(2023, 300), fact(2025, 320)]
    window = S._window_facts(shares, 2022, 2026)
    assert [f.fiscal_year for f in window] == [2023, 2025]
    # Toda la historia daria +220 %; el horizonte de precio solo +6,7 %.
    assert S._series_change(shares) == 2.2
    assert round(S._series_change(window), 3) == 0.067
    assert S._series_change(S._window_facts(shares, 2025, 2026)) is None


def test_trailing_spot_rows_use_close_but_interior_gaps_stay_empty():
    from decimal import Decimal as D
    from types import SimpleNamespace as N

    from app.services.portfolio_intelligence_service import PortfolioIntelligenceService as S

    def row(day, close, adj):
        return N(date=date(2026, 1, day), close=D(close), adj_close=adj if adj is None else D(adj), source="t")

    series = [row(1, "10", "10"), row(2, "11", None), row(3, "12", "12"), row(4, "13", None), row(5, "14", None)]
    filled = S._fill_trailing_spot(series)
    assert [r.adj_close for r in filled] == [D("10"), None, D("12"), D("13"), D("14")]
    assert S._returns(filled) == {date(2026, 1, 4): pytest.approx(13 / 12 - 1), date(2026, 1, 5): pytest.approx(14 / 13 - 1)}
    assert S._fill_trailing_spot([row(1, "10", None)])[0].adj_close is None


def test_horizon_coverage_mide_ventana_real_no_dos_filas():
    service = PortfolioIntelligenceService
    today = date(2026, 10, 16)
    cutoff = date(2025, 10, 16)
    row = lambda d: SimpleNamespace(date=d)
    # Serie completa: ancla al inicio y llega a hoy (con tolerancia).
    share, full = service._horizon_coverage([row(cutoff), row(today)], cutoff, today)
    assert share == pytest.approx(1.0)
    assert full is True
    # Serie de 3 semanas al final: ~6% del horizonte, no cobertura completa,
    # aunque len(series) >= 2 la contaba como "con histórico".
    short = [row(date(2026, 9, 24)), row(date(2026, 10, 16))]
    share, full = service._horizon_coverage(short, cutoff, today)
    assert share == pytest.approx(22 / 365, abs=0.01)
    assert full is False
    # Sin filas: 0 y no completa.
    assert service._horizon_coverage([], cutoff, today) == (0.0, False)
