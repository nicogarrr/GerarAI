"""El peso de cartera del experto no cuenta posiciones sin FX como 0.

``portfolio_concentration`` sumaba ``_num(p.market_value_base) or 0.0``: una
posición abierta sin tipo de cambio (market_value_base None, como la deja el
ledger) valía 0 en el total — inflando el peso de todas las demás — y si la
empresa consultada era la que faltaba, el experto veía "weight_pct: 0.0"
habiendo posición. Ahora se excluyen y se declaran
(``positions_excluded_missing_fx``) y el peso de la propia empresa es None
(desconocido), nunca 0 %. Estos tests fallan sin el arreglo (reversión).
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
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
        aapl = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
                       company_type="operating", valuation_model="dcf")
        gel = Company(ticker="CGEO.L", name="Georgia Capital", exchange="LSE", currency="GEL",
                      company_type="operating", valuation_model="dcf")
        session.add_all([msft, aapl, gel])
        session.flush()
        session.add_all([
            Position(tenant_id=TENANT, company_id=msft.id, quantity=10, average_cost=300,
                     market_value_base=4000.0, currency="USD"),
            Position(tenant_id=TENANT, company_id=aapl.id, quantity=5, average_cost=100,
                     market_value_base=6000.0, currency="USD"),
            # Sin tipo de cambio GEL->EUR: el ledger deja market_value_base None.
            Position(tenant_id=TENANT, company_id=gel.id, quantity=3, average_cost=900,
                     market_value_base=None, currency="GEL"),
        ])
        session.commit()
        yield session
    engine.dispose()


def _weight(db, ticker):
    tools = build_tools(db, today=TODAY)
    out = tools["portfolio_concentration"].fn(RunContext(tenant_id=TENANT, ticker=ticker))
    return out


def test_weight_ignores_and_declares_position_missing_fx(db):
    # Sin el arreglo: la posición GEL contaba 0 en el total y NADIE lo
    # declaraba; weight_pct salía 40.0 con positions_count 3 y sin señal.
    out = _weight(db, "MSFT")
    assert out.data["weight_pct"] == 40.0
    assert out.data["positions_count"] == 3
    assert out.data["positions_excluded_missing_fx"] == 1
    assert out.data["weight_basis"] == "valued_positions_only"


def test_weight_is_unknown_not_zero_when_own_position_missing_fx(db):
    # Repro del bug: sin el arreglo el experto veía weight_pct 0.0 para una
    # empresa con posición abierta. Ahora: None (desconocido) y la exclusión
    # declarada.
    out = _weight(db, "CGEO.L")
    assert out.data["ticker"] == "CGEO.L"
    assert out.data["weight_pct"] is None
    assert out.data["positions_excluded_missing_fx"] == 1
    assert out.data["weight_basis"] == "valued_positions_only"


def test_weight_zero_is_real_when_company_not_held(db):
    session = db
    brk = Company(ticker="BRK.B", name="Berkshire", exchange="NYSE", currency="USD",
                  company_type="operating", valuation_model="dcf")
    session.add(brk)
    session.commit()
    out = _weight(db, "BRK.B")
    assert out.data["weight_pct"] == 0.0


def test_weight_basis_all_positions_when_nothing_excluded(db):
    # Sin posiciones sin FX la base es la cartera completa.
    session = db
    gel = session.query(Company).filter_by(ticker="CGEO.L").one()
    session.query(Position).filter_by(company_id=gel.id).delete()
    session.commit()
    out = _weight(db, "MSFT")
    assert out.data["weight_pct"] == 40.0
    assert out.data["positions_excluded_missing_fx"] == 0
    assert out.data["weight_basis"] == "all_positions"


def test_weight_sums_all_portfolios_of_the_company(db):
    # Dos filas de la misma empresa (dos carteras) con valor en base: suman.
    session = db
    msft = session.query(Company).filter_by(ticker="MSFT").one()
    session.add(Position(tenant_id=TENANT, company_id=msft.id, quantity=10, average_cost=300,
                         market_value_base=2000.0, currency="USD"))
    session.commit()
    out = _weight(db, "MSFT")
    assert out.data["weight_pct"] == 50.0
    assert out.data["positions_excluded_missing_fx"] == 1


def test_toolspec_description_declares_valued_positions_basis(db):
    # La descripción que ve el planificador no puede decir solo "peso en la
    # cartera": declara la base valorada y el contador de excluidas.
    description = build_tools(db, today=TODAY)["portfolio_concentration"].description
    assert "posiciones valoradas" in description
    assert "positions_excluded_missing_fx" in description


def test_risk_prompt_instructs_weight_basis_honesty():
    # El prompt del experto de riesgo cita el campo y prohíbe presentar el
    # peso parcial como el de toda la cartera (ES y EN).
    from app.services import prompt_registry

    definition = prompt_registry.PROMPTS["expert_risk"]
    assert "weight_basis" in definition.text and "valued_positions_only" in definition.text
    assert "toda la cartera" in definition.text
    assert "weight_basis" in definition.text_en and "valued_positions_only" in definition.text_en
    assert "whole portfolio" in definition.text_en
