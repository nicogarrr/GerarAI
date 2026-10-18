"""ChatService._key_facts: latest-per-metric contract and single-query bound.

The chat path is the app's core interaction; its key-facts lookup must stay
one query regardless of how many metrics are configured (it was one query
per metric).
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.chat_service import KEY_FACT_METRICS, ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="CHAT", name="Chat Co", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, metric, value, year):
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="USD", period=f"FY{year}", fiscal_year=year, source_type="filing",
    ))
    db.commit()


def test_latest_fact_per_metric_wins(db):
    c = _company(db)
    _fact(db, c, "revenue", 100, 2024)
    _fact(db, c, "revenue", 130, 2025)
    _fact(db, c, "net_debt", 40, 2024)
    facts = ChatService.__new__(ChatService)._key_facts(db, c)
    by_metric = {f.metric: f.value for f in facts}
    assert by_metric == {"revenue": Decimal("130"), "net_debt": Decimal("40")}
    # Facts follow the canonical KEY_FACT_METRICS order, not alphabetical.
    assert [f.metric for f in facts] == ["revenue", "net_debt"]


def test_single_query_regardless_of_metric_count(db):
    c = _company(db)
    for metric in KEY_FACT_METRICS:
        _fact(db, c, metric, 10, 2025)
    statements = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        facts = ChatService.__new__(ChatService)._key_facts(db, c)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert len(facts) == len(KEY_FACT_METRICS)
    fact_queries = [s for s in statements if "financial_facts" in s]
    assert len(fact_queries) == 1


def test_company_answer_leads_with_what_was_asked(db):
    from app.services.chat_service import _natural_company_answer

    c = _company(db)
    _fact(db, c, "revenue", 130, 2025)
    _fact(db, c, "net_debt", 40, 2025)
    facts = ChatService.__new__(ChatService)._key_facts(db, c)
    base = dict(company=c, facts=facts, thesis=None, news=[], missing_metrics=[], claims=[],
                contradiction_claims=[], price_line="CHAT cotiza a $10.")
    debt = _natural_company_answer(**base, question="¿Cuánta deuda tiene?")
    assert debt.startswith("Deuda neta de CHAT:")
    cash = _natural_company_answer(**base, question="¿Y el efectivo?")
    assert cash.startswith("No tengo guardado ese dato de CHAT")
    risks = _natural_company_answer(**base, question="¿Qué riesgos hay?")
    assert risks.startswith("No tengo riesgos documentados guardados de CHAT")
    thesis = _natural_company_answer(**base, question="¿Cómo va la tesis?")
    assert thesis.startswith("No tengo ninguna tesis guardada de CHAT")
    generic = _natural_company_answer(**base, question="cuéntame de la empresa")
    assert generic.startswith("CHAT cotiza")
