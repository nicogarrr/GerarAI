"""Chat: «¿qué alertas tengo configuradas?» lista tus reglas de aviso activas.

Antes el chat solo daba el número de reglas por tipo («price_below 1»), sin decir
de qué empresa ni con qué umbral. Ahora lista cada regla activa en lenguaje
normal. Solo lectura: no crea ni borra alertas (dice dónde hacerlo).
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import AlertRule, Base, Company
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las reglas no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    companies = {}
    for ticker in ("MSFT", "KO", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        companies[ticker] = company.id
    rules = {1: (("MSFT", "price_below", "<", "300", True, datetime(2026, 10, 20, 15, 0, tzinfo=UTC)),
                 ("KO", "price_change", "<=", "-5", True, None),
                 ("MSFT", "news", ">=", "1", True, None),
                 ("KO", "price_above", ">", "80", False, None)),
             2: (("AAPL", "price_above", ">", "250", True, None),)}
    for tenant, rows in rules.items():
        db.info["tenant_id"] = tenant
        for ticker, kind, op, value, active, fired in rows:
            db.add(AlertRule(tenant_id=tenant, company_id=companies[ticker], name=f"{ticker}: {kind} {op} {value}",
                             rule_type=kind, condition={"operator": op, "value": value}, active=active,
                             last_triggered_at=fired))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué alertas tengo configuradas?", "lista de mis alertas",
                                      "mis reglas de aviso", "¿Qué alertas tengo puestas?"])
def test_lists_active_rules(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") == "account_alert_rules"
    assert resp.answer.startswith("Tienes 3 alertas activas:")
    assert "- MSFT: precio por debajo de 300 USD (saltó por última vez el 20 oct 2026)" in resp.answer
    assert "- KO: variación del día de -5 % o menos" in resp.answer
    assert "- MSFT: noticias nuevas" in resp.answer
    assert "80" not in resp.answer
    assert resp.answer.endswith("Para crear, pausar o borrar alertas, ve a Alertas.")


def test_no_rules():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Qué alertas tengo configuradas?")
    assert resp.answer.startswith("No tienes alertas activas. Puedes crearlas en Alertas.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué alertas tengo configuradas?")
    assert "- AAPL: precio por encima de 250 USD" in resp.answer
    assert "MSFT" not in resp.answer and "KO" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "What alerts do I have set up?")
        assert resp.answer.startswith("You have 3 active alerts:")
        assert "- MSFT: price below 300 USD (last triggered Oct 20, 2026)" in resp.answer
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["mis alertas", "¿Qué alertas tengo de MSFT?", "Avísame si MSFT baja de 300"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_alert_rules"
