"""Bordes de agregacion de pesos en drift_analysis.

Cubre los tres huecos que las 19 suites del carril dejaban sin medir en
investment_plan_service (linea del ``continue`` de valor no positivo, rama
«ticker ya visto en el sector» y la guardia muerta de ``sector in by_label``,
eliminada con su declaracion en el commit).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.investment_plan_service import InvestmentPlanService
from tests.test_investment_plan_service import _plan


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(ticker, sector="Tech"):
    return Company(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency="USD",
        sector=sector,
        industry=sector,
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def _position(company, value):
    return Position(
        company_id=company.id,
        quantity=Decimal("10"),
        market_price=Decimal("100"),
        currency="EUR",
        market_value_base=value,
        as_of=date(2026, 9, 20),
    )


def test_drift_without_plan_reports_absent(db):
    """Sin plan ni cartera: retorno temprano, nunca un analisis inventado."""
    service = InvestmentPlanService()
    assert service.drift_analysis(db) == {"plan_exists": False}


def test_drift_without_default_portfolio_reports_absent(db):
    """Plan sin cartera predeterminada: mismo retorno temprano.

    Ademas mata al mutante ``or`` -> ``and`` de la guardia: con plan y sin
    cartera predeterminada, ``and`` dejaria pasar y portfolio.base_currency
    reventaria mas abajo. (Borrar la cartera no sirve: la FK arrastra el
    plan en cascada y el caso vuelve a ser «sin plan».)
    """
    service = InvestmentPlanService()
    _plan(service, db)
    portfolio = service.fx.portfolio(db)
    portfolio.is_default = False
    db.commit()
    assert service.get_plan(db) is not None
    assert service.drift_analysis(db) == {"plan_exists": False}


def test_zero_and_negative_positions_are_excluded_from_weights(db):
    """Valor base 0 o negativo: ni pesa ni abre su sector; no es «sin precio»."""
    service = InvestmentPlanService()
    _plan(
        service,
        db,
        target_allocations=[{"kind": "asset_class", "label": "Cash", "target_pct": 0, "band_pct": 100}],
    )
    tech, zero, neg = _company("AAPL"), _company("ZERO", sector="ZeroSec"), _company("NEG", sector="NegSec")
    db.add_all([tech, zero, neg])
    db.flush()
    db.add(_position(tech, Decimal("1000")))
    db.add(_position(zero, Decimal("0")))
    db.add(_position(neg, Decimal("-50")))
    db.commit()

    drift = service.drift_analysis(db)
    # 0 y -50 no son «sin valoracion»: no ensucian missing_fx ni el total.
    assert drift["status"] == "ok"
    assert drift["missing_fx"] == []
    assert drift["portfolio_value_base"] == 1000.0
    # Un mutante que deje pasar el 0 (value < 0) o quite el filtro abriria
    # ZeroSec/NegSec con peso 0.0: este assert mata ambos.
    assert drift["current_weights"] == {"Tech": 100.0, "ticker:AAPL": 100.0, "asset_class:Cash": 0.0}


def test_two_positions_same_ticker_accumulate_once_per_sector(db):
    """Dos posiciones del mismo ticker: una entrada por sector, valor sumado."""
    service = InvestmentPlanService()
    _plan(
        service,
        db,
        target_allocations=[{"kind": "ticker", "label": "AAPL", "target_pct": 75, "band_pct": 1}],
    )
    aapl, msft = _company("AAPL"), _company("MSFT")
    db.add_all([aapl, msft])
    db.flush()
    db.add(_position(aapl, Decimal("1000")))
    db.add(_position(aapl, Decimal("500")))  # misma empresa: rama «ticker ya listado»
    db.add(_position(msft, Decimal("500")))
    db.commit()

    drift = service.drift_analysis(db)
    assert drift["status"] == "ok"
    assert drift["portfolio_value_base"] == 2000.0
    # ticker:AAPL agrega las dos posiciones (75 %) y aparece una sola vez; un
    # mutante sin acumulado por sector/ticker (542/543) dejaria 50 % o 25 %.
    assert drift["current_weights"] == {
        "Tech": 100.0,
        "ticker:AAPL": 75.0,
        "ticker:MSFT": 25.0,
        "asset_class:Cash": 0.0,
    }
    dev = {d["label"]: d for d in drift["deviations"]}
    assert dev["AAPL"]["current_pct"] == 75.0
    assert dev["AAPL"]["within_band"] is True
