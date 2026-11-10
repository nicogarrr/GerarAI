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


def test_company_answer_handles_intrinsic_value_and_comparison(db):
    from app.services.chat_service import _natural_company_answer

    c = _company(db)
    _fact(db, c, "revenue", 130, 2025)
    facts = ChatService.__new__(ChatService)._key_facts(db, c)
    base = dict(company=c, facts=facts, thesis=None, news=[], missing_metrics=[], claims=[],
                contradiction_claims=[], price_line="CHAT cotiza a $10.")
    answer = _natural_company_answer(
        **base, question="¿Cuál es el valor intrínseco y qué ingresos usa el modelo? Compáralo con Microsoft."
    )
    # «valor intrínseco» se contesta desde la tesis, no con la cifra de ingresos.
    assert answer.startswith("No tengo ninguna tesis guardada de CHAT")
    assert "No puedo comparar dos empresas" in answer
    plain = _natural_company_answer(**base, question="¿Y los ingresos?")
    assert "No puedo comparar" not in plain


@pytest.mark.parametrize("versions", [4, 40])
def test_only_latest_rows_are_hydrated(db, versions):
    from types import SimpleNamespace

    c = _company(db)
    cid = c.id
    for metric in KEY_FACT_METRICS:
        for i in range(versions):
            db.add(FinancialFact(
                company_id=cid, metric=metric, value=Decimal(i + 1),
                unit="USD", period=f"FY{1980 + i}", fiscal_year=1980 + i,
                source_type="filing",
            ))
    db.commit()
    db.expunge_all()
    loaded = []
    def on_load(_session, obj):
        if isinstance(obj, FinancialFact):
            loaded.append(obj.id)
    event.listen(db, "loaded_as_persistent", on_load)
    try:
        facts = ChatService.__new__(ChatService)._key_facts(db, SimpleNamespace(id=cid))
    finally:
        event.remove(db, "loaded_as_persistent", on_load)
    assert [f.metric for f in facts] == KEY_FACT_METRICS
    assert all(f.value == Decimal(versions) for f in facts)
    assert len(loaded) == len(KEY_FACT_METRICS)


def test_rank_ties_null_year_and_limit(db):
    from datetime import UTC, datetime

    c = _company(db)
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    for value, year in [(10, 2024), (20, 2024), (999, None)]:
        db.add(FinancialFact(company_id=c.id, metric="revenue", value=Decimal(value),
                            unit="USD", period=str(value), fiscal_year=year,
                            created_at=stamp, source_type="test"))
    db.commit()
    service = ChatService.__new__(ChatService)
    assert service._key_facts(db, c)[0].value == Decimal(20)
    assert service._key_facts(db, c, limit=0) == []


def test_rank_cannot_be_displaced_by_foreign_tenant_or_company(db):
    from types import SimpleNamespace

    c = _company(db)
    cid = c.id
    db.info["tenant_id"] = 1
    _fact(db, c, "revenue", 100, 2024)
    other = Company(ticker="OTHER", name="Other", exchange="NYSE", company_type="holding",
                    valuation_model="unassigned")
    db.add(other)
    db.commit()
    _fact(db, other, "revenue", 800, 2030)
    db.info["tenant_id"] = 2
    _fact(db, c, "revenue", 900, 2031)
    db.info["tenant_id"] = 1
    db.expunge_all()
    facts = ChatService.__new__(ChatService)._key_facts(db, SimpleNamespace(id=cid))
    assert [(f.metric, f.value) for f in facts] == [("revenue", Decimal(100))]


def test_key_facts_empty_company(db):
    c = _company(db)
    assert ChatService.__new__(ChatService)._key_facts(db, c) == []
