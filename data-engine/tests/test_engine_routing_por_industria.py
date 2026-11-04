"""Motor de valoración por industria, sin mapa de tickers escrito a mano.

El registro (``resolve_engine_key``) encaminaba los motores sectoriales con un
mapa por ticker (CB, CPT…). La regla de Nico: nada por empresa, todo general.
Un REIT de renta se reconoce por su industria (la de la ficha o, si esa es la
taxonomía gruesa de Finnhub —«Real Estate»—, la de la referencia del
instrumento: «Residential REITs», «Retail REITs»…) y va al motor ``reit``
(NAV por NOI / cap rate; sin datos, respaldo orientativo por múltiplos).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, InstrumentReference
from app.valuation.engines.registry import resolve_engine_key


def _co(ticker="ZZRT", industry="Unknown", company_type="research_candidate", model="unassigned", tags=None):
    return SimpleNamespace(
        ticker=ticker,
        industry=industry,
        company_type=company_type,
        valuation_model=model,
        factor_tags=tags or [],
    )


@pytest.mark.parametrize(
    "industry",
    [
        "REIT - Residential",  # FMP / Yahoo
        "REIT - Industrial",
        "Residential REITs",  # referencia del instrumento (financedatabase)
        "Retail REITs",
        "Health Care REITs",
        "Equity Real Estate Investment Trusts (REITs)",  # GICS
    ],
)
def test_reit_sin_entrada_en_mapa_va_al_motor_reit(industry):
    # Ticker inventado: ningún mapa lo conoce; solo la industria decide.
    assert resolve_engine_key(_co(industry=industry)) == "reit"


@pytest.mark.parametrize(
    "industry",
    [
        "Mortgage REITs",  # cartera de préstamos: no es NAV por NOI
        "REIT - Mortgage",
        "Real Estate Services",  # CBRE: servicios, no REIT
        "Real Estate - Development",  # Zillow / promotoras
        "Real Estate",  # taxonomía gruesa sin más señal
        "Freight & Logistics",  # «reit» dentro de una palabra no cuenta
    ],
)
def test_no_reits_siguen_en_dcf(industry):
    assert resolve_engine_key(_co(industry=industry)) == "standard_dcf"


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


def test_reit_por_referencia_del_instrumento_cuando_la_ficha_es_gruesa():
    # Prod (4-nov-2026): CPT, O, PLD tienen industry «Real Estate» (Finnhub);
    # la referencia del instrumento dice «Residential REITs».
    db = _db()
    company = _company(db, "ZZRT")
    _ref(db, "ZZRT", "Residential REITs")
    assert resolve_engine_key(company) == "reit"


def test_referencia_no_reit_o_de_otra_divisa_no_cambia_el_motor():
    db = _db()
    servicios = _company(db, "ZZSV")
    _ref(db, "ZZSV", "Real Estate Development & Services")
    hipotecario = _company(db, "ZZMR")
    _ref(db, "ZZMR", "Mortgage REITs")
    # Mismo símbolo en otra bolsa: la referencia es de otro instrumento.
    colision = _company(db, "ZZEU", currency="EUR")
    _ref(db, "ZZEU", "Office REITs", currency="USD")
    sin_ref = _company(db, "ZZNO")
    for company in (servicios, hipotecario, colision, sin_ref):
        assert resolve_engine_key(company) == "standard_dcf", company.ticker


def test_tipo_y_modelo_decididos_mandan_sobre_la_industria():
    assert resolve_engine_key(_co(industry="Residential REITs", company_type="asset_manager_holding")) == "holding_company"
    assert resolve_engine_key(_co(industry="Residential REITs", model="sotp")) == "sotp"


def test_antiguas_entradas_cb_y_cpt_resuelven_por_reglas():
    # Con sus datos reales de prod (4-nov-2026), sin mirar el ticker.
    assert resolve_engine_key(_co(ticker="CB", industry="Insurance")) == "insurer"
    db = _db()
    cpt = _company(db, "CPT", industry="Real Estate")
    _ref(db, "CPT", "Residential REITs")
    assert resolve_engine_key(cpt) == "reit"
    # Y el ticker por sí solo ya no fuerza nada.
    assert resolve_engine_key(_co(ticker="CB")) == "standard_dcf"
    assert resolve_engine_key(_co(ticker="CPT")) == "standard_dcf"
