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

    import app.services.portfolio_intelligence_service as pi_module

    # El servicio fecha el valor final con local_today() (hoy en Madrid):
    # congelar ESA base. Parchear date.today ya no gobierna al servicio y en
    # CI (TZ=UTC) entre las 23:00 y 00:00 el valor final quedaba un dia por
    # delante de los flujos y el XIRR se movia lo suficiente para romper las
    # tolerancias.
    monkeypatch.setattr(pi_module, "local_today", lambda: today)
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


def _freeze_today(monkeypatch):
    today = date.today()

    import app.services.portfolio_intelligence_service as pi_module

    # El servicio fecha el valor final con local_today() (hoy en Madrid):
    # congelar ESA base. Parchear date.today ya no gobierna al servicio y en
    # CI (TZ=UTC) entre las 23:00 y 00:00 el valor final quedaba un dia por
    # delante de los flujos y el XIRR se movia lo suficiente para romper las
    # tolerancias.
    monkeypatch.setattr(pi_module, "local_today", lambda: today)
    return today


def test_xirr_sale_proceeds_in_cash_are_not_counted_twice(db, monkeypatch):
    """Caso de la auditoria (xirr_caja_doble_conteo).

    Compra 10 @ 100 hace un ano (-1.000), venta 10 @ 110 hoy (+1.100) y la caja
    del broker queda en 1.100. Sin depositos registrados el XIRR es de
    INVERSION: flujos = compras/ventas/dividendos y valor final = solo
    posiciones (aqui 0). A mano: -1.000 + 1.100/(1+r) = 0 -> r = 10 %.
    Antes se sumaba ademas la caja como valor final: -1.000, +1.100, +1.100
    -> r ~ 120 % (la venta contada dos veces).
    """
    from app.models.entities import CashBalance
    from app.services.portfolio_fx_service import PortfolioFXService

    today = _freeze_today(monkeypatch)
    company = _company(db)
    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.add_all([
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id,
            trade_date=today - timedelta(days=365), action="buy",
            quantity=Decimal("10"), price=Decimal("100"), currency="EUR",
            external_id="xirr-dc-buy",
        ),
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id, trade_date=today,
            action="sell", quantity=Decimal("10"), price=Decimal("110"),
            currency="EUR", external_id="xirr-dc-sell",
        ),
        CashBalance(currency="EUR", balance=Decimal("1100")),
    ])
    db.commit()

    xirr, meta = PortfolioIntelligenceService()._xirr(db, [])
    assert meta["status"] == "calculated"
    assert meta["perspective"] == "investment"
    assert xirr == pytest.approx(0.10, abs=1e-6)


def test_xirr_account_perspective_uses_only_external_flows(db, monkeypatch):
    """Con depositos/retiradas registrados el XIRR es de CUENTA: flujos =
    solo aportaciones y retiradas externas, valor final = posiciones + caja
    (CFA Level I, money-weighted return; GIPS 2020, "external cash flow").

    Deposito de 1.000 hace un ano (IBKR "Deposits/Withdrawals"), compra
    10 @ 100 ese dia, dividendo de 50 a mitad de ano (queda en caja) y hoy
    posicion 1.100 + caja 50. A mano: -1.000 + 1.150/(1+r) = 0 -> r = 15 %.
    La compra y el dividendo son movimientos INTERNOS de la cuenta: ya estan
    dentro del valor final. Antes entraban el deposito como salida (-1.000)
    Y la compra (-1.000): r salia negativo.
    """
    from app.models.entities import CashBalance
    from app.services.portfolio_fx_service import PortfolioFXService

    today = _freeze_today(monkeypatch)
    company = _company(db)
    portfolio = PortfolioFXService().ensure_portfolio(db)
    start = today - timedelta(days=365)
    db.add_all([
        Transaction(
            portfolio_id=portfolio.id, company_id=None, trade_date=start,
            action="cash_misc", quantity=Decimal("1"), price=Decimal("1000"),
            currency="EUR", external_id="xirr-acc-dep",
            raw_payload={"type": "Deposits/Withdrawals"},
        ),
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id, trade_date=start,
            action="buy", quantity=Decimal("10"), price=Decimal("100"),
            currency="EUR", external_id="xirr-acc-buy",
        ),
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id,
            trade_date=start + timedelta(days=184), action="dividend",
            quantity=Decimal("1"), price=Decimal("50"), currency="EUR",
            external_id="xirr-acc-div",
        ),
        CashBalance(currency="EUR", balance=Decimal("50")),
    ])
    position = Position(
        portfolio_id=portfolio.id, company_id=company.id,
        quantity=Decimal("10"), market_price=Decimal("110"),
        market_value_base=Decimal("1100"), currency="EUR", as_of=today,
    )
    db.add(position)
    db.commit()

    xirr, meta = PortfolioIntelligenceService()._xirr(db, [(position, company)])
    assert meta["status"] == "calculated"
    assert meta["perspective"] == "account"
    assert meta["external_flows"] == 1
    assert xirr == pytest.approx(0.15, abs=1e-6)


def test_xirr_account_withdrawal_is_an_inflow_to_the_investor(db, monkeypatch):
    """Deposito manual de 1.000 hace un ano y retirada de 200 hoy; hoy la
    cuenta vale 900 (solo caja). A mano: -1.000 + (200 + 900)/(1+r) = 0
    -> r = 10 %."""
    from app.models.entities import CashBalance
    from app.services.portfolio_fx_service import PortfolioFXService

    today = _freeze_today(monkeypatch)
    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.add_all([
        Transaction(
            portfolio_id=portfolio.id, company_id=None,
            trade_date=today - timedelta(days=365), action="deposit",
            quantity=Decimal("1"), price=Decimal("1000"), currency="EUR",
            external_id="xirr-w-dep",
        ),
        Transaction(
            portfolio_id=portfolio.id, company_id=None, trade_date=today,
            action="withdrawal", quantity=Decimal("1"), price=Decimal("200"),
            currency="EUR", external_id="xirr-w-wd",
        ),
        CashBalance(currency="EUR", balance=Decimal("900")),
    ])
    db.commit()

    xirr, meta = PortfolioIntelligenceService()._xirr(db, [])
    assert meta["perspective"] == "account"
    assert xirr == pytest.approx(0.10, abs=1e-6)


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


def _ns(**kwargs):
    return SimpleNamespace(**kwargs)


def _daily_returns(start: date, days: int, step: float = 0.001):
    return {start + timedelta(days=i): step * (1 if i % 2 == 0 else -1) for i in range(days)}


def test_correlations_below_min_observations_is_none_with_count():
    service = PortfolioIntelligenceService
    start = date(2026, 1, 5)
    left_company = _ns(id=1, ticker="AAA")
    right_company = _ns(id=2, ticker="BBB")
    rows = [(_ns(), left_company), (_ns(), right_company)]
    # 19 sesiones compartidas: por debajo del mínimo, el coeficiente sería ruido.
    returns = {
        1: _daily_returns(start, 19),
        2: _daily_returns(start, 19, step=0.002),
    }
    matrix, observations = service._correlations(returns, rows)
    assert matrix["AAA"]["BBB"] is None
    assert matrix["BBB"]["AAA"] is None
    assert observations["AAA"]["BBB"] == 19
    assert matrix["AAA"]["AAA"] == 1.0


def test_correlations_at_min_observations_is_computed():
    service = PortfolioIntelligenceService
    start = date(2026, 1, 5)
    left_company = _ns(id=1, ticker="AAA")
    right_company = _ns(id=2, ticker="BBB")
    rows = [(_ns(), left_company), (_ns(), right_company)]
    shared = service.MIN_CORRELATION_OBSERVATIONS
    identical = _daily_returns(start, shared)
    returns = {1: dict(identical), 2: dict(identical)}
    matrix, observations = service._correlations(returns, rows)
    assert matrix["AAA"]["BBB"] == pytest.approx(1.0)
    assert observations["AAA"]["BBB"] == shared


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


def test_xirr_withholding_and_fee_negative_amounts_are_outflows(db, monkeypatch):
    """IBKR Flex trae 'Withholding Tax' y 'Other Fees' con importe NEGATIVO.

    Compra -1.000 (hace 365 dias), dividendo +100 y retencion IBKR -15 (dia 184),
    valor final 1.000. Flujos correctos: -1.000, +85, +1.000 -> XIRR = 8,866%.
    Con el signo invertido la retencion sumaba (+115) -> 12,17%.
    """
    today = date.today()

    import app.services.portfolio_intelligence_service as pi_module

    # El servicio fecha el valor final con local_today() (hoy en Madrid):
    # congelar ESA base. Parchear date.today ya no gobierna al servicio y en
    # CI (TZ=UTC) entre las 23:00 y 00:00 el valor final quedaba un dia por
    # delante de los flujos y el XIRR se movia lo suficiente para romper las
    # tolerancias.
    monkeypatch.setattr(pi_module, "local_today", lambda: today)
    company = _company(db)
    service = PortfolioIntelligenceService()
    from app.services.portfolio_fx_service import PortfolioFXService

    portfolio = PortfolioFXService().ensure_portfolio(db)
    start = today - timedelta(days=365)
    mid = start + timedelta(days=184)
    db.add_all([
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id, trade_date=start,
            action="buy", quantity=Decimal("10"), price=Decimal("100"),
            currency="EUR", external_id="xirr-wht-buy",
        ),
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id, trade_date=mid,
            action="dividend", quantity=Decimal("1"), price=Decimal("100"),
            currency="EUR", external_id="xirr-wht-div",
        ),
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id, trade_date=mid,
            action="withholding", quantity=Decimal("1"), price=Decimal("-15"),
            currency="EUR", external_id="xirr-wht-tax",
        ),
    ])
    position = Position(
        portfolio_id=portfolio.id, company_id=company.id,
        quantity=Decimal("10"), market_price=Decimal("100"),
        market_value_base=Decimal("1000"), currency="EUR", as_of=today,
    )
    db.add(position)
    db.commit()

    xirr, meta = service._xirr(db, [(position, company)])
    assert meta["status"] == "calculated"
    # -1000 + 85/(1+r)^(184/365) + 1000/(1+r) = 0  ->  r = 0,088657
    assert xirr == pytest.approx(0.088657, abs=1e-5)


@pytest.mark.parametrize("action", ["buy", "sell", "dividend", "interest", "fee", "withholding"])
def test_xirr_missing_fx_in_investment_flow_is_incomplete(db, monkeypatch, action):
    from app.services.portfolio_fx_service import PortfolioFXService

    today = _freeze_today(monkeypatch)
    company = _company(db)
    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.add_all([
        Transaction(portfolio_id=portfolio.id, company_id=company.id,
                    trade_date=today - timedelta(days=365), action="buy",
                    quantity=1, price=1000, currency="EUR"),
        Transaction(portfolio_id=portfolio.id, company_id=company.id,
                    trade_date=today, action=action,
                    quantity=1, price=100, currency="HKD"),
    ])
    position = Position(portfolio_id=portfolio.id, company_id=company.id,
                        quantity=1, currency="EUR", market_value_base=1100,
                        as_of=today)
    db.add(position)
    db.commit()
    result, trace = PortfolioIntelligenceService()._xirr(db, [(position, company)])
    assert result is None
    assert trace["status"] == "incomplete_missing_fx"
    assert trace["missing_fx"][0]["kind"] == "cashflow"


def test_xirr_account_missing_fx_ending_cash_not_omitted(db, monkeypatch):
    from app.models import CashBalance
    from app.services.portfolio_fx_service import PortfolioFXService

    today = _freeze_today(monkeypatch)
    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.add_all([
        Transaction(portfolio_id=portfolio.id, trade_date=today - timedelta(days=365),
                    action="deposit", quantity=1, price=10000, currency="EUR"),
        CashBalance(currency="EUR", balance=6000),
        CashBalance(currency="HKD", balance=20000),
    ])
    db.commit()
    result, trace = PortfolioIntelligenceService()._xirr(db, [])
    assert result is None
    assert trace["status"] == "incomplete_missing_fx"
    assert trace["missing_fx"] == [{"kind": "ending_cash", "currency": "HKD"}]
    # Synthetic rate, not a market assertion. Supplying it restores coverage.
    PortfolioFXService().upsert_rate(db, base_currency="EUR", quote_currency="HKD",
                                   rate=Decimal("0.12"), rate_date=today, source="test")
    db.commit()
    result, trace = PortfolioIntelligenceService()._xirr(db, [])
    assert trace["status"] == "calculated"
    assert result == pytest.approx(-0.16, abs=1e-4)


def test_xirr_account_internal_missing_fx_does_not_block(db, monkeypatch):
    from app.models import CashBalance
    from app.services.portfolio_fx_service import PortfolioFXService

    today = _freeze_today(monkeypatch)
    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.add_all([
        Transaction(portfolio_id=portfolio.id, trade_date=today - timedelta(days=365),
                    action="deposit", quantity=1, price=1000, currency="EUR"),
        Transaction(portfolio_id=portfolio.id, trade_date=today, action="dividend",
                    quantity=1, price=100, currency="HKD"),
        CashBalance(currency="EUR", balance=1100),
    ])
    db.commit()
    result, trace = PortfolioIntelligenceService()._xirr(db, [])
    assert trace["status"] == "calculated"
    assert result == pytest.approx(0.1, abs=1e-4)


def test_xirr_unknown_position_value_is_not_zero(db, monkeypatch):
    from app.services.portfolio_fx_service import PortfolioFXService

    today = _freeze_today(monkeypatch)
    company = _company(db)
    portfolio = PortfolioFXService().ensure_portfolio(db)
    db.add(Transaction(portfolio_id=portfolio.id, company_id=company.id,
                       trade_date=today - timedelta(days=365), action="buy",
                       quantity=1, price=1000, currency="EUR"))
    position = Position(portfolio_id=portfolio.id, company_id=company.id,
                        quantity=1, currency="HKD", market_value_base=None,
                        market_value=10000, as_of=today)
    db.add(position)
    db.commit()
    result, trace = PortfolioIntelligenceService()._xirr(db, [(position, company)])
    assert result is None
    assert trace["status"] == "incomplete_missing_fx"
    assert trace["missing_fx"][0]["kind"] == "position"
