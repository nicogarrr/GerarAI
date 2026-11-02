"""Chat: «¿cuánto he aportado?» sin «mi» también responde con tu plan.

Antes la regla del plan ya tenía «cuánto he aportado» y «how much have I
contributed», pero exigía además «mi/mis/my» en la frase: «¿Cuánto he
aportado?» o «how much have I contributed so far?» caían al modelo general,
que sin fuentes contestaba «No puedo responderte con fuentes ahora mismo».
Solo lectura y solo del tenant.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, InvestmentPlan, PlanContribution, Portfolio
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el plan no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 1))


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    plans = {1: ("300", date(2026, 6, 1), 20, [{"kind": "ticker", "label": "MSFT", "target_pct": 60},
                                                {"kind": "ticker", "label": "KO", "target_pct": 40}], 4),
             2: ("50", date(2026, 1, 1), 10, [], 1)}
    for tenant, (monthly, start, years, targets, paid) in plans.items():
        db.info["tenant_id"] = tenant
        db.add(Portfolio(tenant_id=tenant, name="Principal", base_currency="EUR"))
        db.flush()
        plan = InvestmentPlan(tenant_id=tenant, monthly_contribution=Decimal(monthly),
                              monthly_contribution_currency="EUR", start_date=start, horizon_years=years,
                              target_allocations=targets)
        db.add(plan)
        db.flush()
        for month in range(paid):
            db.add(PlanContribution(tenant_id=tenant, plan_id=plan.id, date=date(2026, 6 + month, 5),
                                    amount=Decimal(monthly), currency="EUR"))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Cuánto he aportado?", "¿cuánto he aportado hasta ahora?",
                                      "¿Cuánto he aportado este año?"])
def test_contributed_without_possessive(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") == "account_plan"
    assert "Aportado: 1.200,00 € de 1.500,00 € previstos hasta hoy (5 meses); vas 300,00 € por detrás." in resp.answer


@pytest.mark.parametrize("question", ["How much have I contributed?", "how much have I contributed so far?"])
def test_contributed_without_possessive_english(question, monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace.get("path") == "account_plan"
    assert "Contributed: 1,200.00 € of 1,500.00 € expected so far (5 months); 300.00 € behind." in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánto he aportado?")
    assert resp.llm_trace.get("path") == "account_plan"
    assert resp.answer.startswith("Tu plan de aportación: 50,00 € al mes")
    assert "300,00" not in resp.answer and "MSFT" not in resp.answer


def test_ticker_question_is_not_the_plan():
    resp = _ask(_db(), "¿Cuánto he aportado a KO?")
    assert resp.llm_trace.get("path") != "account_plan"
