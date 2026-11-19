"""Regresión: cifras de intelligence de portfolio (auditoría quant Q1-Q4).

Q1: un dividendo manual canónico (quantity=0, price=importe) debe entrar en
    la contribución por posición vía cash_amount, no quantity*price (que lo
    hacía invisible mientras el informe fiscal y _xirr sí lo declaraban).
Q2: los dividendos de la atribución se miden en la MISMA ventana que el
    retorno de precio, no sobre toda la historia del ledger.
Q3: _series_change con base negativa (EPS pre-revenue/turnaround) es N/D:
    último/primero-1 invertía el signo económico (-2 -> -1 = mejora = -50%).
Q4: el residuo `multiple` propaga None cuando el crecimiento fundamental o
    las recompras no están medidos (política null-propagante del método).

Q5 (fallback de subunidades GBp/GBP en build()) espeja la regla ya cubierta
de _xirr (normalize_currency + divisor); sin test dedicado aquí.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    FXRate,
    MarketPrice,
    Portfolio,
    Position,
    Transaction,
)
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _portfolio(db, base="EUR"):
    db.add(Portfolio(name="Main", base_currency=base, is_default=True))
    db.commit()


def _company(db, ticker, currency="USD"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency=currency,
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _position(db, company, *, currency="USD", market_value_base=None):
    position = Position(
        company_id=company.id, quantity=Decimal("10"),
        average_cost=Decimal("10"), cost_basis_native=Decimal("100"),
        market_value=Decimal("200"), market_value_native=Decimal("200"),
        market_value_base=Decimal(str(market_value_base)) if market_value_base is not None else None,
        market_price=Decimal("20"),
        currency=currency, base_currency="EUR",
        fx_rate=Decimal("0.95"), as_of=date(2026, 6, 1),
    )
    db.add(position)
    db.commit()
    return position


def _prices(db, company, rows):
    series = []
    for day, adj in rows:
        price = MarketPrice(
            company_id=company.id, date=day, open=adj, high=adj, low=adj,
            close=adj, adj_close=Decimal(str(adj)), source="test",
        )
        db.add(price)
        series.append(price)
    db.commit()
    return series


def _fx(db, day, rate):
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=day, rate=Decimal(str(rate)), source="test"))
    db.commit()


CUTOFF = date(2026, 1, 1)


def test_q1_ledger_contribution_counts_canonical_manual_dividend(db):
    """Dividendo manual canónico {quantity:0, price:100} EUR dentro del
    horizonte: contribución = end(200) - start(100) + income(100) = 200.
    Con quantity*price el income era 0 y la contribución quedaba en 100."""
    _portfolio(db, "EUR")
    c = _company(db, "Q1DIV", currency="EUR")
    p = _position(db, c, currency="EUR", market_value_base=200)
    _prices(db, c, [(date(2025, 12, 31), 10), (date(2026, 6, 1), 20)])
    db.add(Transaction(
        company_id=c.id, trade_date=date(2025, 6, 1), action="buy",
        quantity=Decimal("10"), price=Decimal("10"), fees=Decimal("0"),
        currency="EUR", raw_payload={},
    ))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 1), action="dividend",
        quantity=Decimal("0"), price=Decimal("100"), fees=Decimal("0"),
        currency="EUR", raw_payload={},
    ))
    db.commit()

    out = PortfolioIntelligenceService()._ledger_contribution(db, [(p, c)], CUTOFF)
    row = out["positions"][0]
    assert row["reason"] is None
    assert row["income"] == pytest.approx(100.0)
    assert row["contribution_pnl"] == pytest.approx(200.0)


def test_q1_ledger_contribution_aliases_and_withholding(db):
    """Alias 'div' cuenta como ingreso; la retención resta (coste), no suma."""
    _portfolio(db, "EUR")
    c = _company(db, "Q1ALI", currency="EUR")
    p = _position(db, c, currency="EUR", market_value_base=200)
    _prices(db, c, [(date(2025, 12, 31), 10), (date(2026, 6, 1), 20)])
    db.add(Transaction(
        company_id=c.id, trade_date=date(2025, 6, 1), action="buy",
        quantity=Decimal("10"), price=Decimal("10"), fees=Decimal("0"),
        currency="EUR", raw_payload={},
    ))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 1), action="div",
        quantity=Decimal("0"), price=Decimal("100"), fees=Decimal("0"),
        currency="EUR", raw_payload={},
    ))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 1), action="withholding",
        quantity=Decimal("0"), price=Decimal("15"), fees=Decimal("0"),
        currency="EUR", raw_payload={},
    ))
    db.commit()

    out = PortfolioIntelligenceService()._ledger_contribution(db, [(p, c)], CUTOFF)
    row = out["positions"][0]
    assert row["reason"] is None
    assert row["income"] == pytest.approx(85.0)


def test_q2_attribution_dividends_windowed_to_price_period(db):
    """Dividendo de 2020 (fuera de la ventana de precios 2026) NO entra en
    dividend_return; solo el del periodo. Antes: 60/100 en vez de 10/100."""
    _portfolio(db)
    c = _company(db, "Q2WIN")
    p = _position(db, c)
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2026, 1, 1), "0.90")
    _fx(db, date(2026, 6, 1), "0.99")
    db.add(Transaction(
        company_id=c.id, trade_date=date(2020, 5, 1), action="dividend",
        quantity=Decimal("0"), price=Decimal("50"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 15), action="dividend",
        quantity=Decimal("0"), price=Decimal("10"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    db.commit()

    out = PortfolioIntelligenceService()._attribution(
        db, [(p, c)], {c.id: 1.0}, {c.id: prices}, CUTOFF
    )
    components = out["positions"][0]["components"]
    assert components["dividends"] == pytest.approx(0.10)


def test_q3_series_change_negative_base_is_nd():
    """EPS -2 -> -1 (mejora) no puede publicarse como -50%: N/D."""
    from app.models.entities import FinancialFact

    svc = PortfolioIntelligenceService
    def fact(year, value):
        return FinancialFact(company_id=1, metric="eps_diluted", fiscal_year=year,
                             value=Decimal(str(value)), source_type="test")
    assert svc._series_change([fact(2020, -2), fact(2021, -1)]) is None
    assert svc._series_change([fact(2020, -1), fact(2021, 2)]) is None
    assert svc._series_change([fact(2020, 0), fact(2021, 2)]) is None
    assert svc._series_change([fact(2020, 2), fact(2021, 4)]) == pytest.approx(1.0)


def test_q4_multiple_nd_when_fundamental_growth_unmeasured(db):
    """Con dividendos conocidos pero sin facts de EPS/acciones en la ventana,
    el residuo no puede absorber el crecimiento no medido como 0: None."""
    _portfolio(db)
    c = _company(db, "Q4MULT")
    p = _position(db, c)
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2026, 1, 1), "0.90")
    _fx(db, date(2026, 6, 1), "0.99")
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 15), action="dividend",
        quantity=Decimal("0"), price=Decimal("10"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    db.commit()

    out = PortfolioIntelligenceService()._attribution(
        db, [(p, c)], {c.id: 1.0}, {c.id: prices}, CUTOFF
    )
    components = out["positions"][0]["components"]
    assert components["dividends"] == pytest.approx(0.10)
    assert components["fundamental_growth"] is None
    assert components["multiple"] is None