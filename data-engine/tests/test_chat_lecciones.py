"""Chat: «¿qué lecciones he aprendido?» / «what lessons have I learned?» con tus lecciones guardadas.

Antes la pregunta caía al modelo general («No puedo responderte con fuentes…»)
aunque las lecciones del diario de decisiones están guardadas. Ahora lista las
aprobadas tal cual se guardaron (sin traducir ni regenerar), la más reciente
primero, y cuenta las propuestas pendientes de revisar; las rechazadas no salen.
Solo lectura y solo del tenant.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, DecisionLesson
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las lecciones guardadas no pasan por el LLM")


def _db(lessons=None):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("KO", "UBER", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    rows = lessons if lessons is not None else (
        (1, "KO", "approved", "Don't buy before earnings without a margin of safety.", datetime(2026, 10, 1, 9, tzinfo=UTC)),
        (1, "UBER", "approved", "Revisar la tesis cuando cambia la guía.", datetime(2026, 10, 20, 9, tzinfo=UTC)),
        (1, None, "proposed", "Propuesta sin revisar.", datetime(2026, 10, 25, 9, tzinfo=UTC)),
        (1, "KO", "rejected", "Rechazada: no sale.", datetime(2026, 10, 26, 9, tzinfo=UTC)),
        (2, "AAPL", "approved", "Lección del otro usuario.", datetime(2026, 10, 27, 9, tzinfo=UTC)),
    )
    for tenant, ticker, status, text, created in rows:
        db.info["tenant_id"] = tenant
        db.add(DecisionLesson(tenant_id=tenant, company_id=ids[ticker] if ticker else None, taxonomy="timing",
                              lesson=text, status=status, created_at=created, updated_at=created))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué lecciones he aprendido?", "¿cuáles son mis lecciones?",
                                      "¿Cuántas lecciones tengo?", "What lessons have I learned?"])
def test_lists_approved_lessons_verbatim(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_lessons"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "Tienes 2 lecciones aprobadas en el diario de decisiones (la más reciente primero):",
        "- UBER (20 oct 2026): Revisar la tesis cuando cambia la guía.",
        "- KO (1 oct 2026): Don't buy before earnings without a margin of safety.",
        "Además hay 1 lección propuesta pendiente de revisar.",
        "Están en el diario de decisiones de cada empresa.",
    ]


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "What lessons have I learned?")
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_lessons"
    assert resp.answer.splitlines() == [
        "You have 2 approved lessons in the decision journal (most recent first):",
        "- UBER (Oct 20, 2026): Revisar la tesis cuando cambia la guía.",
        "- KO (Oct 1, 2026): Don't buy before earnings without a margin of safety.",
        "There is also 1 proposed lesson pending review.",
        "They are in each company's decision journal.",
    ]


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿qué lecciones he aprendido?")
    assert resp.answer.splitlines()[:2] == [
        "Tienes 1 lección aprobada en el diario de decisiones (la más reciente primero):",
        "- AAPL (27 oct 2026): Lección del otro usuario.",
    ]
    for leak in ("KO", "UBER", "Propuesta", "pendiente"):
        assert leak not in resp.answer


def test_only_proposed():
    db = _db(lessons=((1, "KO", "proposed", "Una.", datetime(2026, 10, 1, tzinfo=UTC)),
                      (1, "KO", "proposed", "Otra.", datetime(2026, 10, 2, tzinfo=UTC))))
    resp = _ask(db, "¿qué lecciones he aprendido?")
    assert resp.answer == ("No tienes lecciones aprobadas todavía. Hay 2 lecciones propuestas pendientes de revisar "
                           "en el diario de decisiones de cada empresa.")


def test_none():
    resp = _ask(_db(lessons=()), "¿qué lecciones he aprendido?")
    assert resp.answer == ("No tienes lecciones guardadas. Salen al revisar las decisiones del diario "
                           "de cada empresa.")


@pytest.mark.parametrize("question", ["¿Qué lecciones dejó la crisis de 2008?", "what lessons did Buffett learn?"])
def test_general_lessons_are_not_mine(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_lessons"


def test_sources_link_each_company_journal():
    resp = _ask(_db(), "¿qué lecciones he aprendido?")
    assert [src["url"] for src in resp.sources] == ["/research/UBER/decision-lessons", "/research/KO/decision-lessons"]
