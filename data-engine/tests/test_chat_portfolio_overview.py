"""'Mi cartera' se responde con las posiciones guardadas, sin LLM y sin recomendar."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker, name):
    comp = Company(ticker=ticker, name=name, exchange="NYSE", company_type="holding", valuation_model="unassigned")
    db.add(comp)
    db.flush()
    return comp


def test_mi_cartera_lists_stored_positions_without_llm(db):
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), currency="EUR", market_value=Decimal("300")))
    db.add(Position(tenant_id=1, company_id=b.id, quantity=Decimal("2"), average_cost=Decimal("50"), currency="EUR", market_value=Decimal("100")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué tengo en mi cartera?", "portfolio", None))
    assert resp.model == "deterministic"
    assert resp.llm_trace["provider_calls"] == 0
    assert "2 posiciones" in resp.answer
    assert resp.answer.index("AAA") < resp.answer.index("BBB")
    assert "75 %" in resp.answer
    assert "recomendación" not in resp.answer
    assert {s["type"] for s in resp.sources} == {"position"}


def test_order_verbs_and_empty_portfolio_keep_the_old_route(db):
    a = _company(db, "AAA", "Alpha")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), market_value=Decimal("300")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "Vende mi cartera", "portfolio", None))
    assert resp.prompt_version != "portfolio-overview-v1"


def test_other_tenant_positions_never_appear_and_no_tenant_means_no_overview(db):
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "SECRET", "Other tenant co")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), market_value=Decimal("300")))
    db.commit()
    db.info["tenant_id"] = 2
    db.add(Position(tenant_id=2, company_id=b.id, quantity=Decimal("99"), average_cost=Decimal("1"), market_value=Decimal("9999")))
    db.commit()
    db.info["tenant_id"] = 1
    resp = asyncio.run(ChatService().answer(db, "¿Qué tengo en mi cartera?", "portfolio", None))
    assert "AAA" in resp.answer and "SECRET" not in resp.answer and "1 posiciones" in resp.answer
    db.info["tenant_id"] = None
    assert ChatService()._portfolio_overview(db) is None


def test_mixed_base_currencies_show_no_total_or_weights(db):
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("1"), average_cost=Decimal("5"), market_value=Decimal("300"), base_currency="EUR"))
    db.add(Position(tenant_id=1, company_id=b.id, quantity=Decimal("1"), average_cost=Decimal("5"), market_value=Decimal("100"), base_currency="USD"))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "mis posiciones", "portfolio", None))
    assert "sin total" in resp.answer and "%" not in resp.answer


def test_followup_uses_history_to_rank_positions(db):
    from app.schemas import ChatTurn

    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), market_value=Decimal("300")))
    db.add(Position(tenant_id=1, company_id=b.id, quantity=Decimal("2"), average_cost=Decimal("50"), market_value=Decimal("100")))
    db.commit()
    history = [
        ChatTurn(role="user", content="¿Qué tengo en mi cartera?"),
        ChatTurn(role="assistant", content="Tu cartera guardada tiene 2 posiciones abiertas"),
    ]
    resp = asyncio.run(
        ChatService().answer(db, "¿cuál tiene el coste medio más alto?", "portfolio", None, history=history)
    )
    assert resp.prompt_version == "portfolio-ranking-v1"
    assert "BBB" in resp.answer and "50" in resp.answer
    assert resp.llm_trace["provider_calls"] == 0
    low = asyncio.run(
        ChatService().answer(db, "¿y el de menor valor?", "portfolio", None, history=history)
    )
    assert "BBB" in low.answer


def test_ranking_without_portfolio_history_is_not_hijacked(db):
    a = _company(db, "AAA", "Alpha")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), market_value=Decimal("300")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿cuál tiene el coste medio más alto?", "portfolio", None))
    assert resp.prompt_version != "portfolio-ranking-v1"


def test_ranking_refuses_to_compare_mixed_currencies(db):
    from app.schemas import ChatTurn

    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), currency="EUR", base_currency="EUR", market_value=Decimal("300"), market_value_base=Decimal("300")))
    db.add(Position(tenant_id=1, company_id=b.id, quantity=Decimal("2"), average_cost=Decimal("50"), currency="USD", base_currency="USD", market_value=Decimal("100"), market_value_base=Decimal("100")))
    db.commit()
    history = [ChatTurn(role="assistant", content="Tu cartera guardada tiene 2 posiciones abiertas")]
    for question in ("¿cuál tiene el coste medio más alto?", "¿cuál tiene el mayor valor?"):
        resp = asyncio.run(ChatService().answer(db, question, "portfolio", None, history=history))
        assert resp.prompt_version == "portfolio-ranking-v1"
        assert "monedas distintas" in resp.answer
        assert "EUR" in resp.answer and "USD" in resp.answer
        assert resp.llm_trace["mixed_currency"] is True


def test_risk_question_about_my_portfolio_is_not_answered_with_the_positions_table(db):
    a = _company(db, "AAA", "Alpha")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), currency="EUR", market_value=Decimal("300")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué riesgos tiene mi cartera?", "portfolio", None))
    assert resp.prompt_version == "portfolio-analysis-v1"
    assert (resp.llm_trace or {}).get("path") == "portfolio_analysis"
    assert "Mayor posición: AAA" in resp.answer
    assert "100 %" in resp.answer or "100,0 %" in resp.answer
    assert "no son un análisis de riesgos de mercado" in resp.answer
    # La pregunta de listado sigue por el volcado de posiciones.
    listing = asyncio.run(ChatService().answer(db, "¿Qué tengo en mi cartera?", "portfolio", None))
    assert listing.prompt_version == "portfolio-overview-v1"


def test_analysis_never_sums_unconverted_native_values(db):
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("1"), average_cost=Decimal("5"), currency="USD",
                    base_currency="EUR", market_value=Decimal("1000"), market_value_base=Decimal("900")))
    db.add(Position(tenant_id=1, company_id=b.id, quantity=Decimal("1"), average_cost=Decimal("5"), currency="USD",
                    base_currency="EUR", market_value=Decimal("1000")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué riesgos tiene mi cartera?", "portfolio", None))
    assert "Mayor posición: AAA" in resp.answer
    assert "100 %" in resp.answer
    assert "BBB" in resp.answer.split("Sin valor en moneda base")[1]
