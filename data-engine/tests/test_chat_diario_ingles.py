"""Chat: el diario de decisiones en inglés y sin «1 abiertas».

Antes «my decision journal» o «what decisions have I logged?» iban al modelo
general (el diario solo se reconocía en español) y la respuesta española decía
«1 abiertas de las últimas 1 registradas». Solo lectura y solo del tenant.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, DecisionJournalEntry
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el diario no debe pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("UBER", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    for tenant, ticker, rationale in ((1, "UBER", "Margen operativo al alza"), (2, "AAPL", "Servicios crecen")):
        db.info["tenant_id"] = tenant
        db.add(DecisionJournalEntry(tenant_id=tenant, company_id=ids[ticker], decision_date=date(2026, 10, 1),
                                    decision="buy", rationale=rationale, price=Decimal("45.2"),
                                    what_must_be_true=["Margen > 10 %"]))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_spanish_singular():
    resp = _ask(_db(), "mi diario de decisiones")
    assert resp.llm_trace["path"] == "decision_journal"
    assert resp.answer.startswith("Diario de decisiones: 1 abierta de la única registrada.")
    assert "- UBER, 1 oct 2026: comprar a 45,20 (abierta). Motivo: Margen operativo al alza" in resp.answer
    assert "AAPL" not in resp.answer


@pytest.fixture()
def english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("question", ["my decision journal", "Show my investment journal",
                                      "What decisions have I logged?", "my recent decisions"])
def test_english_journal_without_llm(english, question):
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "decision_journal"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.startswith("Decision journal: 1 open of the only one recorded.")
    assert "- UBER, Oct 1, 2026: buy at 45.20 (open). Reason: Margen operativo al alza" in resp.answer
    assert "Must hold true: 1 condition." in resp.answer
    assert "Diario" not in resp.answer and "Motivo" not in resp.answer


def test_user_b_never_sees_user_a(english):
    db = _db()
    db.info["tenant_id"] = 2
    db.info["language"] = "en"
    resp = _ask(db, "my decision journal")
    assert "AAPL" in resp.answer
    assert "UBER" not in resp.answer and "Margen" not in resp.answer
