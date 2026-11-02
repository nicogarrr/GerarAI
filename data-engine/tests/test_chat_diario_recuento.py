"""Chat: el diario de decisiones cuenta todas las entradas y se lee en castellano.

- «how many journal entries do I have?» iba al modelo general («I can't answer
  with sources…»); ahora va al diario, como «¿cuántas entradas tengo en el diario?».
- Con más de 40 entradas, la cabecera decía «de las últimas 40 registradas» y
  solo contaba las abiertas de esas 40; ahora cuenta todas (abiertas y total).
- En castellano una decisión revisada salía «(reviewed)» y «1 condición(es)».
Solo lectura y solo del tenant.
"""

import asyncio
from datetime import date, timedelta

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


def _db(many=False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("KO", "AAPL"):
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
    db.info["tenant_id"] = 1
    db.add(
        DecisionJournalEntry(
            tenant_id=1,
            company_id=ids["KO"],
            decision="buy",
            rationale="Dividendo estable",
            decision_date=date(2026, 10, 1),
            status="reviewed",
            what_must_be_true=["el dividendo sube"],
        )
    )
    db.add(
        DecisionJournalEntry(
            tenant_id=1,
            company_id=ids["KO"],
            decision="hold",
            rationale="Sigo",
            decision_date=date(2020, 1, 1),
            status="open",
        )
    )
    if many:
        for n in range(45):
            db.add(
                DecisionJournalEntry(
                    tenant_id=1,
                    company_id=ids["KO"],
                    decision="watch",
                    rationale=f"nota {n}",
                    decision_date=date(2026, 1, 1) + timedelta(days=n),
                    status="reviewed",
                )
            )
    db.commit()
    db.info["tenant_id"] = 2
    for n in range(3):
        db.add(
            DecisionJournalEntry(
                tenant_id=2,
                company_id=ids["AAPL"],
                decision="buy",
                rationale=f"otra {n}",
                decision_date=date(2026, 5, 1),
                status="open",
            )
        )
    db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.fixture
def _en(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("_en")
@pytest.mark.parametrize("question", ["How many journal entries do I have?", "show my journal entries"])
def test_english_journal_entries(question):
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "decision_journal"
    assert resp.answer.splitlines()[0] == "Decision journal: 1 open of the last 2 recorded."


def test_spanish_reads_in_spanish():
    resp = _ask(_db(), "¿cuántas entradas tengo en el diario?")
    assert resp.llm_trace["path"] == "decision_journal"
    assert "(reviewed)" not in resp.answer
    assert "- KO, 1 oct 2026: comprar (revisada). Motivo: Dividendo estable Debe cumplirse: 1 condición." in (
        resp.answer
    )


def test_counts_every_entry_past_the_shown_ones():
    resp = _ask(_db(many=True), "mi diario de decisiones")
    assert resp.answer.splitlines()[0] == "Diario de decisiones: 1 abierta de 47 registradas."
    # La abierta más antigua sigue saliendo aunque no esté entre las 40 últimas.
    assert "- KO, 1 ene 2020: mantener (abierta). Motivo: Sigo" in resp.answer


@pytest.mark.usefixtures("_en")
def test_counts_every_entry_english():
    db = _db(many=True)
    db.info["language"] = "en"
    resp = _ask(db, "my decision journal")
    assert resp.answer.splitlines()[0] == "Decision journal: 1 open of 47 recorded."


def test_user_b_never_sees_user_a():
    db = _db(many=True)
    db.info["tenant_id"] = 2
    resp = _ask(db, "mi diario de decisiones")
    assert resp.answer.splitlines()[0] == "Diario de decisiones: 3 abiertas de las últimas 3 registradas."
    assert "KO" not in resp.answer
