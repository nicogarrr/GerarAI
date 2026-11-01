"""Chat: «¿qué posición va peor/mejor?» ordena tus posiciones por rentabilidad.

Antes el ranking solo existía por valor/peso/coste; ahora hay ranking por
rentabilidad sobre el coste de compra, encabezado por la peor o la mejor según
la pregunta. Solo lectura y solo tus posiciones.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, Position
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el ranking no debe pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    data = {1: (("UBER", 30, "2400", "1500"), ("MSFT", 5, "1800", "1200"), ("ASTS", 100, "900", "1200"),
                ("KO", 10, "600", "0")),
            2: (("AAPL", 10, "5000", "1000"),)}
    for tenant, positions in data.items():
        db.info["tenant_id"] = tenant
        for ticker, q, v, c in positions:
            company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                              valuation_model="unassigned", currency="USD")
            db.add(company)
            db.flush()
            db.add(Position(tenant_id=tenant, company_id=company.id, quantity=Decimal(q),
                            average_cost=Decimal(c) / q, market_value=Decimal(v), market_value_native=Decimal(v),
                            market_value_base=Decimal(v), cost_basis_native=Decimal(c), cost_basis_base=Decimal(c),
                            currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30)))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué posición va peor?", "¿Cuál es mi peor inversión?",
                                      "¿qué acción me da menos rentabilidad?"])
def test_worst_first(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.answer.startswith("La que peor va sobre su coste: ASTS -25,0 % (-300,00 €).")
    assert "1. ASTS -25,0 % (-300,00 €)\n2. MSFT +50,0 % (+600,00 €)\n3. UBER +60,0 % (+900,00 €)" in resp.answer
    assert "Sin coste o valor guardado, fuera: KO." in resp.answer


@pytest.mark.parametrize("question", ["¿Cuál es mi mejor posición?", "ranking de mis posiciones por rentabilidad",
                                      "¿Qué acción me da más rentabilidad?"])
def test_best_first(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.answer.startswith("La que mejor va sobre su coste: UBER +60,0 % (+900,00 €).")
    assert "1. UBER +60,0 %" in resp.answer and "3. ASTS -25,0 %" in resp.answer
    assert "AAPL" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué posición va peor?")
    assert "AAPL +400,0 %" in resp.answer and "UBER" not in resp.answer and "ASTS" not in resp.answer
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Qué posición va peor?")
    assert resp.answer.startswith("No tienes posiciones abiertas con valor y coste guardados")


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "Which is my worst performing position?")
        assert resp.answer.startswith("Worst return on cost: ASTS -25.0% (-300.00 €).")
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["¿Cuál es la mejor acción para comprar?", "ranking de mis posiciones",
                                      "¿Cómo va UBER?"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") != "account_return_ranking"
