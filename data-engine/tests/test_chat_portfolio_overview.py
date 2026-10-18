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
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, name):
    comp = Company(ticker=ticker, name=name, exchange="NYSE", company_type="holding", valuation_model="unassigned")
    db.add(comp)
    db.flush()
    return comp


def test_mi_cartera_lists_stored_positions_without_llm(db):
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    db.add(Position(company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), market_value=Decimal("300")))
    db.add(Position(company_id=b.id, quantity=Decimal("2"), average_cost=Decimal("50"), market_value=Decimal("100")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué tengo en mi cartera?", "portfolio", None))
    assert resp.model == "deterministic"
    assert resp.llm_trace["provider_calls"] == 0
    assert "2 posiciones" in resp.answer
    assert resp.answer.index("AAA") < resp.answer.index("BBB")
    assert "75 %" in resp.answer
    assert "no una recomendación" in resp.answer
    assert {s["type"] for s in resp.sources} == {"position"}


def test_order_verbs_and_empty_portfolio_keep_the_old_route(db):
    a = _company(db, "AAA", "Alpha")
    db.add(Position(company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("5"), market_value=Decimal("300")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "Vende mi cartera", "portfolio", None))
    assert resp.prompt_version != "portfolio-overview-v1"
