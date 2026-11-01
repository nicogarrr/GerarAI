"""Chat: «mi plan de aportación» / «mis planes DCA» con tu plan guardado.

Antes «mis planes DCA» solo daba los niveles DCA y «¿cuánto he aportado a mi
plan?» no tenía respuesta: el plan de aportación (cuota, inicio, reparto
objetivo y aportado frente a previsto) no llegaba al chat. Solo lectura.
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


@pytest.mark.parametrize("question", ["¿Cuál es mi plan de aportación?", "mi plan de inversión",
                                      "¿Cuánto he aportado a mi plan?", "¿Voy al día con mi plan?"])
def test_plan(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") == "account_plan"
    assert resp.answer.startswith("Tu plan de aportación: 300,00 € al mes desde el 1 jun 2026, a 20 años.")
    assert "Aportado: 1.200,00 € de 1.500,00 € previstos hasta hoy (5 meses); vas 300,00 € por detrás." in resp.answer
    assert "Reparto objetivo: MSFT 60 %, KO 40 %." in resp.answer
    assert "Para cambiarlo, ve a Plan." in resp.answer


def test_dca_plans_include_plan_and_levels():
    resp = _ask(_db(), "mis planes DCA")
    assert resp.llm_trace.get("path") == "account_plan"
    assert resp.answer.startswith("Tu plan de aportación: 300,00 € al mes")
    assert "Sin nivel DCA" in resp.answer


def test_no_plan():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Cuál es mi plan de aportación?")
    assert resp.answer.startswith("No tienes un plan de aportación guardado. Puedes crearlo en Plan.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuál es mi plan de aportación?")
    assert resp.answer.startswith("Tu plan de aportación: 50,00 € al mes desde el 1 ene 2026, a 10 años.")
    assert "MSFT" not in resp.answer and "300" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "What is my investment plan?")
        assert resp.answer.startswith("Your contribution plan: 300.00 € a month since Jun 1, 2026, over 20 years.")
        assert "Contributed: 1,200.00 € of 1,500.00 € expected so far (5 months); 300.00 € behind." in resp.answer
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["Tengo 500 € este mes. Según mi plan, ¿qué compro?", "nivel DCA de MSFT",
                                      "¿Qué es un plan de pensiones?"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_plan"
