"""Chat: «¿qué carteras tengo?» / «how many portfolios do I have?» lista tus carteras.

Antes caían al modelo general («No puedo responderte con fuentes…»). Ahora
lista cada cartera guardada con sus posiciones abiertas, su valor en su divisa
base y cuál es la predeterminada. Solo lectura y solo del tenant.
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
        raise AssertionError("las carteras no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("KO", "ITX", "TSLA"):
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
    layout = {
        1: (
            ("Principal", "EUR", True, (("KO", "10", "550"), ("ITX", "5", "200"), ("TSLA", "0", "0"))),
            ("Hijos", "USD", False, (("KO", "2", "120"),)),
            ("Vacía", "EUR", False, ()),
        ),
        2: (("Secreta", "EUR", True, (("TSLA", "100", "25000"),)),),
    }
    for tenant, portfolios in layout.items():
        db.info["tenant_id"] = tenant
        for name, base, default, positions in portfolios:
            p = Portfolio(tenant_id=tenant, name=name, base_currency=base, is_default=default)
            db.add(p)
            db.flush()
            for ticker, qty, value in positions:
                db.add(
                    Position(
                        tenant_id=tenant,
                        portfolio_id=p.id,
                        company_id=ids[ticker],
                        quantity=Decimal(qty),
                        average_cost=Decimal("1"),
                        market_value_base=Decimal(value),
                        currency="USD",
                        base_currency=base,
                        as_of=datetime(2026, 10, 30, tzinfo=UTC),
                    )
                )
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué carteras tengo?", "¿cuántas carteras tengo?", "mis carteras"])
def test_lists_portfolios(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_portfolios"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "Tienes 3 carteras guardadas:",
        "- Principal (predeterminada): 2 posiciones abiertas, valor 750,00 €.",
        "- Hijos: 1 posición abierta, valor 120,00 USD.",
        "- Vacía: sin posiciones abiertas.",
        "Valor de las posiciones en la divisa base de cada cartera, con los últimos precios guardados.",
    ]


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué carteras tengo?")
    assert resp.answer.splitlines()[:2] == [
        "Tienes 1 cartera guardada:",
        "- Secreta: 1 posición abierta, valor 25.000,00 €.",
    ]
    assert "Principal" not in resp.answer


def test_no_portfolios():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Qué carteras tengo?")
    assert resp.answer == "No tienes carteras guardadas. Puedes crearlas o importarlas en Cartera."


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How many portfolios do I have?")
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_portfolios"
    assert resp.answer.splitlines()[:4] == [
        "You have 3 saved portfolios:",
        "- Principal (default): 2 open positions, value 750.00 €.",
        "- Hijos: 1 open position, value 120.00 USD.",
        "- Vacía: no open positions.",
    ]


@pytest.mark.parametrize(
    "question", ["¿Cómo va mi cartera?", "¿Qué tengo en mi cartera?", "¿qué cartera me recomiendas?"]
)
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_portfolios"
