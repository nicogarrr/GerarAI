"""FX attribution and XIRR honesty tests (auditor findings on #615).

- _period_fx_return anchors both legs to the real period: a stale
  Position.fx_rate (as_of before the cutoff) must NOT produce an inverted
  return; missing FX stays None.
- _attribution never folds None into 0: an unknown component leaves the
  portfolio aggregate None and declares incompleteness.
- _xirr survives cash rows with FX (Decimal x float used to raise TypeError).
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


def _eur_portfolio(db):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
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


def _position(db, company, *, as_of, fx_rate=None, currency="USD"):
    position = Position(
        company_id=company.id, quantity=Decimal("10"),
        average_cost=Decimal("10"), cost_basis_native=Decimal("100"),
        market_value=Decimal("200"), market_price=Decimal("20"),
        currency=currency, base_currency="EUR",
        fx_rate=Decimal(str(fx_rate)) if fx_rate is not None else None,
        as_of=as_of,
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


def test_fx_return_uses_table_legs_anchored_to_period(db):
    _eur_portfolio(db)
    c = _company(db, "FXA")
    position = _position(db, c, as_of=date(2026, 6, 1), fx_rate="0.95")
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2026, 1, 1), "0.90")
    _fx(db, date(2026, 6, 1), "0.99")

    svc = PortfolioIntelligenceService()
    fx_table = svc and __import__("app.services.portfolio_fx_service", fromlist=["PortfolioFXService"]).PortfolioFXService().fx_table(
        db, currencies={"USD", "EUR"}, base_currency="EUR", as_of_max=date(2026, 6, 1)
    )
    result = svc._period_fx_return(fx_table, position, "EUR", CUTOFF, prices[-1].date)
    assert result == pytest.approx(0.99 / 0.90 - 1)


def test_stale_position_spot_does_not_invert_fx_return(db):
    """as_of before the cutoff: the old code compared the stale spot against
    the cutoff rate and published an inverted return. Now: None."""
    _eur_portfolio(db)
    c = _company(db, "FXB")
    # Spot from last year, table has no rates at all -> fallback would be the
    # stale spot, which must be rejected.
    position = _position(db, c, as_of=date(2025, 6, 1), fx_rate="0.80")
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])

    svc = PortfolioIntelligenceService()
    result = svc._period_fx_return({}, position, "EUR", CUTOFF, prices[-1].date)
    assert result is None


def test_attribution_missing_fx_declares_incomplete_totals(db):
    """Mixed portfolio: one position with FX coverage, one without. The fx
    aggregate must be None (declared incomplete), never a partial 0.0."""
    _eur_portfolio(db)
    c1 = _company(db, "WITH")
    c2 = _company(db, "WITHOUT", currency="GBP")
    p1 = _position(db, c1, as_of=date(2026, 6, 1), fx_rate="0.95")
    p2 = _position(db, c2, as_of=date(2026, 6, 1), fx_rate=None, currency="GBP")
    s1 = _prices(db, c1, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    s2 = _prices(db, c2, [(date(2026, 1, 2), 50), (date(2026, 6, 1), 55)])
    _fx(db, date(2026, 1, 1), "0.90")
    _fx(db, date(2026, 6, 1), "0.99")

    svc = PortfolioIntelligenceService()
    out = svc._attribution(
        db,
        [(p1, c1), (p2, c2)],
        {c1.id: 0.5, c2.id: 0.5},
        {c1.id: s1, c2.id: s2},
        CUTOFF,
    )
    by_ticker = {p["ticker"]: p for p in out["positions"]}
    assert by_ticker["WITH"]["fx_known"] is True
    assert by_ticker["WITHOUT"]["fx_known"] is False
    assert by_ticker["WITH"]["components"]["fx"] == pytest.approx(0.99 / 0.90 - 1)
    assert by_ticker["WITHOUT"]["components"]["fx"] is None
    # Null never folds into 0: the aggregate is None and says why.
    assert out["portfolio_components"]["fx"] is None
    assert out["portfolio_components"]["multiple"] is None
    assert "fx" in out["incomplete_components"]
    assert "multiple" in out["incomplete_components"]


def test_xirr_with_cash_dividend_row_and_fx_does_not_raise(db):
    """Cash row (amount in price, quantity 0) + FX table: Decimal x float
    used to raise TypeError and take down GET /portfolio/intelligence."""
    _eur_portfolio(db)
    c = _company(db, "XIR")
    position = _position(db, c, as_of=date(2026, 6, 1), fx_rate="0.95")
    position.market_value_base = Decimal("209")
    db.commit()
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 1, 15), action="buy",
        quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 15), action="dividend",
        quantity=Decimal("0"), price=Decimal("25.00"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    _fx(db, date(2026, 1, 1), "0.90")
    db.commit()

    value, meta = PortfolioIntelligenceService()._xirr(db, [(position, c)])
    assert value is not None
    assert meta.get("status") in (None, "calculated")


def test_single_initial_rate_never_serves_as_both_legs(db):
    """Tabla con SOLO la tasa del corte: sin tolerancia la misma fila era
    pata inicial y final y publicaba 0,0% medido. Ahora None."""
    _eur_portfolio(db)
    c = _company(db, "FXC")
    position = _position(db, c, as_of=date(2025, 6, 1), fx_rate=None)
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2026, 1, 1), "0.90")

    svc = PortfolioIntelligenceService()
    from app.services.portfolio_fx_service import PortfolioFXService
    fx_table = PortfolioFXService().fx_table(
        db, currencies={"USD", "EUR"}, base_currency="EUR", as_of_max=date(2026, 6, 1)
    )
    assert svc._period_fx_return(fx_table, position, "EUR", CUTOFF, prices[-1].date) is None
    out = svc._attribution(db, [(position, c)], {c.id: 1.0}, {c.id: prices}, CUTOFF)
    assert out["positions"][0]["fx_known"] is False
    assert out["portfolio_components"]["fx"] is None
    assert "fx" in out["incomplete_components"]


def test_old_initial_fx_rate_is_not_a_period_return(db):
    """FX inicial de 2020 con periodo 2026: sin frescura en la pata inicial
    publicaba la variacion de anos como retorno del periodo. Ahora None."""
    _eur_portfolio(db)
    c = _company(db, "FXD")
    position = _position(db, c, as_of=date(2026, 6, 1), fx_rate=None)
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2020, 6, 1), "0.80")
    _fx(db, date(2026, 6, 1), "1.10")

    from app.services.portfolio_fx_service import PortfolioFXService
    fx_table = PortfolioFXService().fx_table(
        db, currencies={"USD", "EUR"}, base_currency="EUR", as_of_max=date(2026, 6, 1)
    )
    svc = PortfolioIntelligenceService()
    assert svc._period_fx_return(fx_table, position, "EUR", prices[0].date, prices[-1].date) is None


def test_fx_start_anchors_to_first_price_bar_not_generic_cutoff(db):
    """Repro del auditor: FX 0.80 ene / 0.90 mar / 1.10 jun, serie de
    precios mar-jun. El FX atribuible al periodo es mar-jun (+22,22%),
    no ene-jun (+37,5%)."""
    _eur_portfolio(db)
    c = _company(db, "FXE")
    position = _position(db, c, as_of=date(2026, 6, 1), fx_rate=None)
    prices = _prices(db, c, [(date(2026, 3, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2026, 1, 5), "0.80")
    _fx(db, date(2026, 3, 1), "0.90")
    _fx(db, date(2026, 6, 1), "1.10")

    svc = PortfolioIntelligenceService()
    out = svc._attribution(db, [(position, c)], {c.id: 1.0}, {c.id: prices}, date(2026, 1, 1))
    fx = out["positions"][0]["components"]["fx"]
    assert fx == pytest.approx(1.10 / 0.90 - 1)
    assert fx != pytest.approx(1.10 / 0.80 - 1)


def test_xirr_excludes_ambiguous_cash_rows_and_declares_coverage(db):
    """A historical non-canonical cash row (qty 100 x price 0.25) must not
    enter XIRR as a certain cashflow: it is excluded and the exclusion is
    declared in the meta."""
    _eur_portfolio(db)
    c = _company(db, "XAMB")
    position = _position(db, c, as_of=date(2026, 6, 1), fx_rate="0.95")
    position.market_value_base = Decimal("209")
    db.commit()
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 1, 15), action="buy",
        quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 15), action="dividend",
        quantity=Decimal("100"), price=Decimal("0.25"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    _fx(db, date(2026, 1, 1), "0.90")
    db.commit()

    value, meta = PortfolioIntelligenceService()._xirr(db, [(position, c)])
    # XIRR sin un flujo de importe desconocido NO es la rentabilidad completa:
    # None + estado explicito, nunca un "calculated" parcial.
    assert value is None
    assert meta["status"] == "incomplete_ambiguous_cash"
    assert meta["ambiguous_cash_excluded"] == 1


def test_attribution_ambiguous_dividends_leave_component_unknown(db):
    """Non-canonical dividend row: the dividends component of that company
    is unknown (None), the aggregate declares incompleteness, and the
    residual multiple is not fabricated by subtracting an invented figure."""
    _eur_portfolio(db)
    c = _company(db, "ATTRAMB")
    p = _position(db, c, as_of=date(2026, 6, 1), fx_rate="0.95")
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2026, 1, 1), "0.90")
    _fx(db, date(2026, 6, 1), "0.99")
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 15), action="dividend",
        quantity=Decimal("100"), price=Decimal("0.25"), fees=Decimal("0"),
        currency="USD", raw_payload={},
    ))
    db.commit()

    svc = PortfolioIntelligenceService()
    out = svc._attribution(db, [(p, c)], {c.id: 1.0}, {c.id: prices}, CUTOFF)
    position = out["positions"][0]
    assert position["dividends_known"] is False
    assert position["components"]["dividends"] is None
    assert position["components"]["multiple"] is None
    assert out["portfolio_components"]["dividends"] is None
    assert "dividends" in out["incomplete_components"]


def test_attribution_no_ledger_or_share_facts_is_nd_not_zero(db):
    """Sin dividendos registrados ni cifras de acciones en el horizonte, los
    componentes son N/D (None), no un 0,0 % que parece medido; el horizonte
    real del retorno de precio viaja en la respuesta."""
    _eur_portfolio(db)
    c = _company(db, "ATTRND")
    p = _position(db, c, as_of=date(2026, 6, 1), fx_rate="0.95")
    prices = _prices(db, c, [(date(2026, 1, 2), 100), (date(2026, 6, 1), 110)])
    _fx(db, date(2026, 1, 1), "0.90")
    _fx(db, date(2026, 6, 1), "0.99")

    out = PortfolioIntelligenceService()._attribution(
        db, [(p, c)], {c.id: 1.0}, {c.id: prices}, CUTOFF
    )
    components = out["positions"][0]["components"]
    assert components["dividends"] is None
    assert components["buybacks"] is None
    assert components["dilution"] is None
    assert out["positions"][0]["period_start"] == "2026-01-02"
    assert out["period_start"] == "2026-01-02"
    assert out["period_end"] == "2026-06-01"
    assert out["basis"] == "adjusted_price_return"
