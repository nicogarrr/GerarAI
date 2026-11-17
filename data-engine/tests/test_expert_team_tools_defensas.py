"""Rutas defensivas de las herramientas del equipo experto (fichero tocado por fix17).

Fijan por la vía pública de cada herramienta lo que ya prometía el código:
sin ticker o sin datos la herramienta devuelve None/[] en vez de romperse o
inventar, un motor de valoración caído no es evidencia, y la ganancia latente
sin P&L persistido se deriva de mercado menos coste cuando ambos existen.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    FinancialFact,
    Position,
)
from app.services import valuation_service
from app.services.expert_team import RunContext, build_tools

TODAY = date(2026, 11, 1)
TENANT = 1


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        msft = Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD",
                       company_type="operating", valuation_model="dcf")
        empty = Company(ticker="EMPTY", name="Sin posiciones", exchange="X", currency="EUR",
                        company_type="operating", valuation_model="dcf")
        session.add_all([msft, empty])
        session.flush()
        session.add_all([
            FinancialFact(tenant_id=TENANT, company_id=msft.id, metric="revenue", value=245.0,
                          unit="USD_bn", period="FY", fiscal_year=2025, source_type="SEC",
                          source_id="10-K-2025", is_reported=True),
            # Sin ejercicio: fuera del conjunto de años, se descarta.
            FinancialFact(tenant_id=TENANT, company_id=msft.id, metric="revenue", value=1.0,
                          unit="USD_bn", period="FY", fiscal_year=None, source_type="SEC",
                          source_id="10-K-2025", is_reported=True),
        ])
        session.commit()
        yield session
    engine.dispose()


def _fn(db, name, **ctx_kwargs):
    return build_tools(db, today=TODAY)[name].fn(RunContext(tenant_id=TENANT, **ctx_kwargs))


def test_concentration_without_ticker_is_none(db):
    assert _fn(db, "portfolio_concentration") is None


def test_financial_facts_skips_yearless_and_valueless_rows(db):
    out = _fn(db, "financial_facts", ticker="MSFT")
    assert len(out) == 1
    assert out[0].data["values"] == {"revenue": 245.0}
    assert out[0].source["date"] == "2025"


def test_valuation_engine_unknown_ticker_is_empty(db):
    assert _fn(db, "valuation_engine", ticker="NOPE") == []


def test_valuation_engine_survives_a_down_engine(db, monkeypatch):
    def boom(self, db, company, *, as_of=None):
        raise RuntimeError("motor caído")

    monkeypatch.setattr(valuation_service.ValuationService, "value_company", boom)
    out = _fn(db, "valuation_engine", ticker="MSFT")
    assert out == []


def test_valuation_engine_ignores_empty_result(db, monkeypatch):
    monkeypatch.setattr(
        valuation_service.ValuationService, "value_company",
        lambda self, db, company, *, as_of=None: {"model_type": None},
    )
    assert _fn(db, "valuation_engine", ticker="MSFT") == []


def test_user_position_unknown_ticker_is_none(db):
    assert _fn(db, "user_position", ticker="NOPE") is None


def test_user_position_without_open_rows_is_none(db):
    assert _fn(db, "user_position", ticker="EMPTY") is None


def test_sale_tax_estimate_derives_gain_from_market_minus_cost(db):
    session = db
    msft = session.query(Company).filter_by(ticker="MSFT").one()
    session.add(Position(
        tenant_id=TENANT, company_id=msft.id, quantity=2, average_cost=350,
        market_value_base=1000.0, cost_basis_base=700.0, unrealized_pnl_base=None,
        currency="USD", base_currency="EUR",
    ))
    session.commit()
    out = _fn(db, "sale_tax_estimate", ticker="MSFT")
    assert out is not None
    assert out.data["gain_if_sold_all"] == 300.0
    assert out.data["base_currency"] == "EUR"
    assert out.data["irpf_if_sold_all"] > 0
