"""Respaldo por comparables de holdings y financieras: nunca sobre cifras consolidadas.

Antes (main 95a9c193d): BN, sin datos de su motor de holding, caia al respaldo
por multiplos con EV/Ventas 6,3x sobre 75.100 M de ingresos CONSOLIDADOS y
publicaba 71/98/111 $ contra 41,38 $ (bajista 1,7x el precio). Ahora: en un
holding, aseguradora o banco solo valen PER o P/VC; el resto se retiene con su
motivo y los valores que se habrian dado quedan en la traza (no se pierden).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company
from app.services import valuation_service as vs


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.info["tenant_id"] = 2
        yield session
    eng.dispose()


def _company(db, ticker):
    c = Company(ticker=ticker, name=ticker, exchange="NYSE", currency="USD", sector="S", industry="I",
                company_type="operating", valuation_model="unassigned", special_sources=[], special_risks=[],
                factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _insufficient(engine):
    return {"status": "insufficient_data", "publishable": False, "missing_inputs": ["holding_company_discount"],
            "base_value": None, "expected_value": None, "trace": {"engine": engine, "reason": "SOTP requires ..."}}


def _cross(headline):
    return {"status": "ok", "bear_value": 71.37, "base_value": 98.29, "bull_value": 110.99,
            "expected_value": 95.0, "margin_of_safety": 0.2, "headline_multiple": headline, "peer_median": 6.34}


@pytest.mark.parametrize("engine", ["holding_company", "insurer", "bank"])
@pytest.mark.parametrize("headline", ["ev_to_sales", "ev_to_ebitda", "p_to_fcf"])
def test_holding_y_financieras_no_usan_multiplos_consolidados(monkeypatch, db, engine, headline):
    monkeypatch.setattr(vs, "_relative_multiples_cross_check", lambda *a, **k: _cross(headline))
    out = vs._sector_fallback(db, _company(db, "BN"), object(), _insufficient(engine), to_listing=None,
                              price_currency="USD", reporting_currency="USD")
    assert out["status"] == "insufficient_data"
    assert out["base_value"] is None
    withheld = out["trace"]["sector_engine_fallback_withheld"]
    assert withheld["headline_multiple"] == headline
    assert withheld["indicative_values"]["base_value"] == 98.29  # no se pierde: queda en la traza
    assert "consolidadas" in withheld["reason"]


@pytest.mark.parametrize("headline", ["pe", "pb"])
def test_holding_con_multiplo_atribuible_sigue_dando_respaldo(monkeypatch, db, headline):
    monkeypatch.setattr(vs, "_relative_multiples_cross_check", lambda *a, **k: _cross(headline))
    out = vs._sector_fallback(db, _company(db, "BN"), object(), _insufficient("holding_company"), to_listing=None,
                              price_currency="USD", reporting_currency="USD")
    assert out["status"] == "partial" and out["base_value"] == 98.29


def test_empresa_operativa_mantiene_ev_ventas(monkeypatch, db):
    monkeypatch.setattr(vs, "_relative_multiples_cross_check", lambda *a, **k: _cross("ev_to_sales"))
    out = vs._sector_fallback(db, _company(db, "XYZ"), object(), _insufficient("reit"), to_listing=None,
                              price_currency="USD", reporting_currency="USD")
    assert out["status"] == "partial"
