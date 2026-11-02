"""Chat: «¿qué posiciones tengo en pérdidas?» / «which positions are losing money?».

Antes en castellano contestaba con la rentabilidad total de la cartera (sin decir
cuáles pierden) y en inglés caía al modelo general. Ahora lista solo las
posiciones en pérdidas (o en ganancias) sobre su coste de compra, la peor
primero. Solo lectura y solo del tenant.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, Portfolio, Position
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las pérdidas no deben pasar por el LLM")


def _db(all_winning=False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("KO", "ITX", "TSLA", "NVDA"):
        company = Company(
            ticker=ticker,
            name=ticker + " Inc",
            exchange="NYSE",
            company_type="consumer",
            valuation_model="unassigned",
            currency="USD",
        )
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    if all_winning:
        layout = {1: (("NVDA", "1200", "1000"),)}
    else:
        layout = {
            1: (("KO", "550", "650"), ("ITX", "180", "200"), ("TSLA", "1500", "1000")),
            2: (("NVDA", "10", "1000"),),
        }
    for tenant, positions in layout.items():
        db.info["tenant_id"] = tenant
        p = Portfolio(tenant_id=tenant, name="Principal", base_currency="EUR", is_default=True)
        db.add(p)
        db.flush()
        for ticker, value, cost in positions:
            db.add(
                Position(
                    tenant_id=tenant,
                    portfolio_id=p.id,
                    company_id=ids[ticker],
                    quantity=Decimal("10"),
                    average_cost=Decimal("1"),
                    market_price=Decimal("1"),
                    market_value_base=Decimal(value),
                    cost_basis_base=Decimal(cost),
                    currency="USD",
                    base_currency="EUR",
                    as_of=datetime(2026, 10, 30, tzinfo=UTC),
                )
            )
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize(
    "question", ["¿Qué posiciones tengo en pérdidas?", "¿qué acciones de mi cartera están en negativo?"]
)
def test_losers(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.answer.splitlines() == [
        "Tienes 2 posiciones en pérdidas sobre su coste de compra (datos a 30 oct 2026), la peor primero:",
        "1. KO -15,4 % (-100,00 €)",
        "2. ITX -10,0 % (-20,00 €)",
        "Rentabilidad simple desde la compra, sin dividendos.",
    ]


def test_winners():
    resp = _ask(_db(), "¿Qué posiciones tengo en ganancias?")
    assert resp.answer.splitlines()[:2] == [
        "Tienes 1 posición en ganancias sobre su coste de compra (datos a 30 oct 2026), la mejor primero:",
        "1. TSLA +50,0 % (+500,00 €)",
    ]


def test_no_losers():
    resp = _ask(_db(all_winning=True), "¿Qué posiciones tengo en pérdidas?")
    assert resp.answer.splitlines()[0] == (
        "Ninguna de tus posiciones está en pérdidas sobre su coste de compra (datos a 30 oct 2026)."
    )


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué posiciones tengo en pérdidas?")
    assert "1. NVDA -99,0 % (-990,00 €)" in resp.answer
    assert "KO" not in resp.answer


@pytest.mark.parametrize(
    "question", ["Which positions are losing money?", "which of my stocks are in the red?"]
)
def test_english(monkeypatch, question):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.answer.splitlines()[:3] == [
        "You have 2 positions at a loss on their purchase cost (data as of Oct 30, 2026), worst first:",
        "1. KO -15.4% (-100.00 €)",
        "2. ITX -10.0% (-20.00 €)",
    ]


@pytest.mark.parametrize("question", ["¿Cuál es mi peor posición?", "¿qué pasa si KO entra en pérdidas?"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert not (resp.answer or "").startswith("Tienes 2 posiciones en pérdidas")
