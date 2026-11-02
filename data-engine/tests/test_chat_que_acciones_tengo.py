"""Chat: «¿qué acciones tengo?» responde con tus posiciones, sin el modelo.

Antes «¿qué acciones tengo?», «¿en qué empresas estoy invertido?» o «what stocks
do I own?» iban al modelo general (y sin modelo, a «No puedo responderte…»),
aunque el volcado de posiciones ya existía para «mis posiciones». Solo lectura
y solo del tenant.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el volcado de posiciones no pasa por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant, ticker in ((1, "UBER"), (2, "AAPL")):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        db.info["tenant_id"] = tenant
        db.add(Position(tenant_id=tenant, company_id=company.id, quantity=Decimal("30"), average_cost=Decimal("50"),
                        market_value=Decimal("2400"), market_value_base=Decimal("2400"), currency="EUR",
                        base_currency="EUR", as_of=date(2026, 10, 30)))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué acciones tengo?", "¿qué empresas tengo en cartera?",
                                      "¿En qué empresas estoy invertido?", "¿Qué tengo en mi cartera?",
                                      "What stocks do I own?", "what do I hold?"])
def test_holdings_question_lists_positions(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert resp.llm_trace["provider_calls"] == 0
    assert "UBER" in resp.answer
    assert "AAPL" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué acciones tengo?")
    assert "AAPL" in resp.answer and "UBER" not in resp.answer


@pytest.mark.parametrize("question", ["¿Qué acciones tengo que vender?", "¿Cuántas acciones tengo de UBER?",
                                      "¿qué acciones tengo que comprar este mes?"])
def test_other_questions_are_not_the_overview(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "portfolio_overview"
