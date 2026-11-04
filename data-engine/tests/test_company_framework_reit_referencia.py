"""Marco de tesis de un REIT por la misma regla que su motor de valoración.

#4527 manda al motor ``reit`` a los REITs de renta por su industria (la de la
ficha o, si esa es la taxonomía gruesa de Finnhub «Real Estate», la de la
referencia del instrumento). El marco de tesis (drivers/KPIs) seguía mirando
solo la ficha y un mapa por ticker (CB, CPT): un REIT como O o PLD quedaba con
motor ``reit`` y marco genérico de caja libre. Marco y motor deben coincidir,
sin tickers escritos a mano.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, InstrumentReference
from app.services.company_framework import resolve_company_framework
from app.valuation.engines.registry import resolve_engine_key


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _company(db: Session, ticker: str, *, industry: str = "Real Estate", currency: str = "USD") -> Company:
    company = Company(
        ticker=ticker,
        name=f"{ticker} Inc.",
        exchange="NYSE",
        currency=currency,
        sector="Real Estate",
        industry=industry,
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _ref(db: Session, ticker: str, industry: str, *, currency: str = "USD") -> None:
    db.add(
        InstrumentReference(
            ticker_normalized=ticker,
            name=f"{ticker} ref",
            industry=industry,
            currency=currency,
            as_of=date(2026, 10, 1),
            source="financedatabase",
        )
    )
    db.flush()


def test_reit_por_referencia_tiene_marco_reit_igual_que_su_motor():
    db = _db()
    company = _company(db, "ZZRT")  # ficha «Real Estate» (Finnhub), como O/PLD en prod
    _ref(db, "ZZRT", "Retail REITs")
    assert resolve_engine_key(company) == "reit"
    assert resolve_company_framework(company).key == "reit"


def test_referencia_no_reit_o_de_otra_divisa_deja_marco_generico():
    db = _db()
    servicios = _company(db, "ZZSV")
    _ref(db, "ZZSV", "Real Estate Development & Services")
    colision = _company(db, "ZZEU", currency="EUR")
    _ref(db, "ZZEU", "Office REITs", currency="USD")
    for company in (servicios, colision):
        assert resolve_company_framework(company).key == "generic_fcf", company.ticker


def _co(ticker: str, industry: str = "Unknown"):
    return SimpleNamespace(
        ticker=ticker,
        industry=industry,
        company_type="research_candidate",
        valuation_model="unassigned",
        factor_tags=[],
    )


def test_cb_y_cpt_por_reglas_y_no_por_ticker():
    # Con sus datos reales de prod (4-nov-2026).
    assert resolve_company_framework(_co("CB", "Insurance")).key == "insurer"
    db = _db()
    cpt = _company(db, "CPT")
    _ref(db, "CPT", "Residential REITs")
    assert resolve_company_framework(cpt).key == "reit"
    # El ticker solo ya no decide el marco.
    assert resolve_company_framework(_co("CB")).key == "generic_fcf"
    assert resolve_company_framework(_co("CPT")).key == "generic_fcf"
