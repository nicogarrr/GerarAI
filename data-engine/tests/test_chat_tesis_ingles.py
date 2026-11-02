"""Chat: «what's the status of my theses?» y «my theses» en inglés.

Antes, en inglés, «my theses» o «what's the status of my theses?» iban al
modelo general (solo se reconocía «tesis») y, sin modelo, contestaba «I can't
answer with sources right now». Ahora listan las tesis guardadas sin el
modelo, en inglés. Solo lectura y solo del tenant.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, ThesisVersion
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las tesis guardadas no deben pasar por el LLM")


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
        db.add(ThesisVersion(tenant_id=tenant, company_id=company.id, version=1, status="published",
                             thesis_markdown="# Tesis", executive_summary="Resumen"))
        db.add(ThesisVersion(tenant_id=tenant, company_id=company.id, version=2, status="draft",
                             thesis_markdown="# Tesis", executive_summary="Resumen"))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.fixture()
def english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _english_db():
    db = _db()
    db.info["language"] = "en"
    return db


@pytest.mark.parametrize("question", ["What's the status of my theses?", "my theses",
                                      "Which theses do I have?", "my investment theses"])
def test_english_theses_without_llm(english, question):
    resp = _ask(_english_db(), question)
    assert resp.llm_trace["path"] == "portfolio_theses"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.startswith("Active theses (latest published per company):")
    assert "- UBER: thesis v1 (published)." in resp.answer
    assert "- UBER: v2, not active (draft or pending publication)." in resp.answer
    assert "Tesis" not in resp.answer and "publicada" not in resp.answer
    assert [s["title"] for s in resp.sources] == ["Thesis UBER v1", "Latest version UBER v2"]


def test_user_b_never_sees_user_a(english):
    db = _english_db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "my theses")
    assert "AAPL" in resp.answer and "UBER" not in resp.answer


def test_spanish_unchanged():
    resp = _ask(_db(), "¿Cuál es el estado de mis tesis?")
    assert resp.llm_trace["path"] == "portfolio_theses"
    assert resp.answer.startswith("Tesis activas (última publicada por empresa):")
    assert "- UBER: tesis v1 (publicada)." in resp.answer
    assert "AAPL" not in resp.answer


def test_english_invalidation_question_not_taken(english):
    resp = _ask(_english_db(), "When are my theses invalidated?")
    assert (resp.llm_trace or {}).get("path") != "portfolio_theses"
