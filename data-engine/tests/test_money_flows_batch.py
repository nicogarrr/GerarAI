"""El payload SEC de un tema consultaba empresa y facts de uno en uno
(~3 consultas por gastador, 7 gastadores en centros-de-datos).

Ahora: 1 consulta de empresas + 1 de facts para todo el tema.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Tenant
from app.services import money_flows
from app.services.money_flows import FLOW_THEMES, build_theme_payload
from tests.test_money_flows import _seed_capex


@pytest.fixture(autouse=True)
def _clear_flow_cache():
    money_flows._cache.clear()
    yield
    money_flows._cache.clear()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_theme_payload_batches_company_and_fact_reads(db):
    _seed_capex(db, ticker="GOOGL", tenant_id=1)
    _seed_capex(db, ticker="MSFT", tenant_id=1)
    _seed_capex(db, ticker="META", tenant_id=None)
    statements = []
    engine = db.get_bind()

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "FROM companies" in statement or "FROM financial_facts" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        payload = build_theme_payload(db, FLOW_THEMES["centros-de-datos"], tenant=1)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    by_table = {"companies": 0, "financial_facts": 0}
    for s in statements:
        if "FROM companies" in s:
            by_table["companies"] += 1
        if "FROM financial_facts" in s:
            by_table["financial_facts"] += 1
    assert by_table == {"companies": 1, "financial_facts": 1}, by_table

    amounts = {s["ticker"]: s["amount"] for s in payload["spenders"]}
    assert amounts["GOOGL"] == 35_700_000_000
    assert amounts["MSFT"] == 35_700_000_000
    assert amounts["META"] == 35_700_000_000
    assert amounts["AMZN"] is None
    assert payload["spenders_total"]["amount"] == 3 * 35_700_000_000
    assert "3 de 7 gastadores incluidos" in payload["spenders_total"]["note"]
