"""Equipo de expertos: las fuentes de valoración y riesgo enlazan a su pantalla cuando la hay.

Las cifras del motor de valoración y de la tesis guardada salían en «Fuentes»
sin enlace aunque la app tiene una pantalla que las enseña: ahora el motor
lleva a la ficha en «Valoración» y la tesis a «Tesis»; el peso en cartera
(experto de riesgo) lleva a «Cartera». Las alertas de riesgo (risk_events)
no tienen pantalla ni URL propia: siguen sin enlace (no se inventa ninguno).
SQLite en memoria, motor de valoración simulado, sin red.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position, RiskEvent, ThesisVersion
from app.services.expert_team import RunContext, build_tools
from app.services.expert_team.view import _url


@pytest.fixture()
def db(monkeypatch):
    from app.services import valuation_service

    monkeypatch.setattr(
        valuation_service.ValuationService,
        "value_company",
        lambda self, db, company: {"model_type": "dcf", "base_value": 410.0, "trace": {"price_as_of": "2026-10-30"}},
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        brk = Company(ticker="BRK.B", name="Berkshire", exchange="NYSE", currency="USD",
                      company_type="operating", valuation_model="dcf")
        session.add(brk)
        session.flush()
        session.add_all([
            ThesisVersion(tenant_id=1, company_id=brk.id, version=3, thesis_markdown="t", executive_summary="s",
                          base_value=Decimal(400)),
            RiskEvent(tenant_id=1, company_id=brk.id, severity="high", event_type="drawdown", message="Cae 20 %"),
            Position(tenant_id=1, company_id=brk.id, quantity=Decimal(10), currency="USD",
                     market_value_base=Decimal(1000)),
        ])
        session.commit()
        yield session


def _run(db, tool):
    out = build_tools(db, today=date(2026, 11, 1))[tool].fn(RunContext(tenant_id=1, ticker="BRK.B"))
    return out if isinstance(out, list) else [out]


def test_valuation_engine_links_to_the_valuation_view(db):
    by_table = {o.source["table"]: o.source for o in _run(db, "valuation_engine")}
    assert by_table["valuation_engine"]["url"] == "/research/BRK.B?view=valoracion"
    assert by_table["thesis_versions"]["url"] == "/research/BRK.B?view=thesis"


def test_portfolio_weight_links_to_the_portfolio(db):
    (out,) = _run(db, "portfolio_concentration")
    assert out.source["url"] == "/portfolio"


def test_risk_events_have_no_invented_link(db):
    (out,) = _run(db, "risk_events")
    assert not out.source.get("url")


def test_saved_thesis_keeps_internal_links_and_drops_others():
    assert _url({"url": "/research/BRK.B?view=valoracion"}) == "/research/BRK.B?view=valoracion"
    assert _url({"url": "/portfolio"}) == "/portfolio"
    assert _url({"url": "https://www.sec.gov/x"}) == "https://www.sec.gov/x"
    assert _url({"url": "//evil.example/x"}) is None
    assert _url({"url": "/research/X?view=valoracion&next=//evil"}) is None
    assert _url({"url": "javascript:alert(1)"}) is None
