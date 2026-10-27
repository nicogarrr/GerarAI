"""Do not silently substitute a historical or alternative sale for today's question."""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position, Transaction
from app.services.chat_service import ChatService
from app.services.sale_hypothetical import parse_purchase_lots, simulate_hypothetical_sale
from app.services.tax_sale_intent import sale_intent_issue

CASE = "Compré 10 acciones a 10 euros el 1 de enero de 2026 y vendí 4 a 12 euros el 1 de marzo de 2026, ¿qué IRPF si vendo 6 a 5 euros?"


class NoLLM:
    name = "none"

    async def complete(self, *args, **kwargs):
        raise AssertionError("No external model for sale clarification")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def assert_clarifies(resp):
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.llm_trace["provider_calls"] == 0
    assert "IRPF estimado" not in resp.answer
    assert "valor 48,00" not in resp.answer
    assert "confirma" in resp.answer.lower()


def test_original_counterexample_hypothetical_never_prices_past_sale(db):
    response = ChatService()._hypothetical_sale_answer(db, CASE, parse_purchase_lots(CASE), None, "TEST")
    assert_clarifies(response)
    assert "venta pasada" in response.answer


def test_original_counterexample_full_route(db):
    response = asyncio.run(ChatService(provider=NoLLM()).answer(db, CASE, "global", None))
    assert_clarifies(response)
    assert "no reconstruye ventas previas" in response.answer


def test_saved_position_also_does_not_select_first_sale(db):
    c = Company(ticker="TEST", name="Synthetic", currency="EUR", exchange="XETRA",
                company_type="holding", valuation_model="unassigned")
    db.add(c)
    db.flush()
    db.add(Transaction(tenant_id=1,company_id=c.id,trade_date=date(2026,1,1),
                       action="buy",quantity=Decimal(10),price=Decimal(10),fees=Decimal(0),currency="EUR"))
    db.add(Position(tenant_id=1,company_id=c.id,quantity=Decimal(10),average_cost=Decimal(10),
                    market_value=Decimal(50),market_value_base=Decimal(50),cost_basis_base=Decimal(100),
                    currency="EUR",base_currency="EUR",as_of=date(2026,10,27)))
    db.commit()
    q = "Vendí 4 acciones de TEST a 12 euros y quiero saber el IRPF si vendo 6 a 5 euros"
    response = asyncio.run(ChatService(provider=NoLLM()).answer(db,q,"global",None))
    assert_clarifies(response)
    assert "venta pasada" in response.answer


@pytest.mark.parametrize("question", [
    "Vendí 4 a 12 euros, ¿IRPF si vendo 6 a 5?",
    "He vendido 4 acciones y si vendo las demás a 5 euros, ¿IRPF?",
    "Ya había vendido 4 acciones; ¿qué IRPF si vendo 6?",
    "Venta anterior de 4 acciones a 12 y hoy vendo 6 a 5, ¿IRPF?",
    "Ya hubo una venta de 4 a 12 en marzo y hoy vendo 6 a 5, ¿IRPF?",
    "¿Qué IRPF si vendo 4 a 12 euros o vendo 6 a 5 euros?",
    "Si vendiera 4 a 12 y vendiese 6 a 5, ¿qué IRPF?",
])
def test_historical_and_multiple_sale_clauses_clarify(question):
    assert sale_intent_issue(question)


@pytest.mark.parametrize("question", [
    "Compré 10 a 10 euros y si vendo 6 a 5 euros, ¿qué IRPF?",
    "Si vendo 10 acciones de TEST a 20 euros, ¿IRPF?",
    "¿IRPF si vendiera la mitad?",
    "¿IRPF por vender 10 acciones?",
    "He comprado 10 acciones y venderé todas mañana",
])
def test_one_sale_and_purchase_history_are_not_rejected(question):
    assert sale_intent_issue(question) is None


def test_simulation_helper_also_returns_no_amount_for_historical_sale(db):
    result = simulate_hypothetical_sale(db, lots=parse_purchase_lots(CASE), question=CASE,
                                        company=None, today=date(2026, 10, 27))
    assert result.sale_price is None
    assert result.gain_eur is None
    assert result.tax_eur is None
    assert result.quantity == 0
    assert "venta pasada" in result.missing[0]


@pytest.mark.parametrize("clause", [
    "Ahora estoy vendiendo 4 a 12 euros o vendo 6 a 5 euros",
    "Primero venderemos 4 a 12 euros y luego vendo 6 a 5 euros",
    "No vendo 4 a 12 euros sino 6 a 5 euros",
    "No he vendido ninguna; ¿IRPF si vendo 6 a 5 euros?",
])
def test_reviewer_conjugations_and_negated_corrections_never_price(db, clause):
    question = "Compré 10 acciones a 10 euros el 1 de enero de 2026. " + clause + ", ¿qué IRPF?"
    result = simulate_hypothetical_sale(db, lots=parse_purchase_lots(question), question=question,
                                        company=None, today=date(2026, 10, 27))
    assert result.sale_price is None and result.gain_eur is None and result.tax_eur is None
    response = ChatService()._hypothetical_sale_answer(db, question, parse_purchase_lots(question), None, "TEST")
    assert "IRPF estimado" not in response.answer
    assert response.llm_trace["clarification"] == "sale_clause_intent"
    if "No " in clause:
        assert "negada" in response.answer
        assert "Has incluido una venta pasada" not in response.answer
