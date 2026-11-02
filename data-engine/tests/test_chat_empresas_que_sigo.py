"""Chat: «¿qué empresas sigo?» responde con tu watchlist.

Antes «¿qué empresas sigo?» o «which companies am I following?» iban al modelo
general (sin modelo, «No puedo responderte…») aunque «mi watchlist» ya tenía
respuesta con los datos guardados. Solo lectura y solo del tenant.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, WatchItem
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant, symbol in ((1, "NVDA"), (2, "TSLA")):
        db.info["tenant_id"] = tenant
        db.add(WatchItem(tenant_id=tenant, symbol=symbol, company=symbol + " Corp"))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué empresas sigo?", "¿cuáles acciones sigo?",
                                      "Which companies am I following?", "what stocks do I watch?"])
def test_followed_companies_are_the_watchlist(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "personal_context"
    # Mismo número de llamadas que antes (la ruta general también llamaba al
    # modelo), pero ahora con la watchlist en el contexto; sin modelo, la
    # respuesta determinista la lista.
    assert resp.llm_trace["intent"] == "watchlist"
    assert "NVDA" in resp.answer
    assert "TSLA" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué empresas sigo?")
    assert "TSLA" in resp.answer and "NVDA" not in resp.answer


@pytest.mark.parametrize("question", ["¿Qué empresas sigue Buffett?", "¿qué empresas sigo comprando?"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "personal_context" or "NVDA" not in resp.answer
