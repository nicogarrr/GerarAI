"""Chat en inglés: «how much have I invested?» y «how much do I contribute a month?».

En castellano «¿cuánto he invertido?» ya daba el coste de compra guardado y
«¿cuánto aporto al mes?» el plan; en inglés las dos caían al modelo general
(«I can't answer with sources…»). Ahora van a las mismas respuestas. Además
«¿cuánto aporto al mes?» va a la respuesta del plan sin modelo. Solo lectura.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, InvestmentPlan, Portfolio, Position
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 2))


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    company = Company(
        ticker="KO",
        name="KO Inc",
        exchange="NYSE",
        company_type="consumer",
        valuation_model="unassigned",
        currency="USD",
    )
    db.add(company)
    db.flush()
    db.info["tenant_id"] = 1
    p = Portfolio(tenant_id=1, name="Principal", base_currency="EUR", is_default=True)
    db.add(p)
    db.flush()
    db.add(
        Position(
            tenant_id=1,
            portfolio_id=p.id,
            company_id=company.id,
            quantity=Decimal("10"),
            average_cost=Decimal("70"),
            market_price=Decimal("60"),
            market_value=Decimal("600"),
            market_value_base=Decimal("550"),
            cost_basis_base=Decimal("650"),
            unrealized_pnl_base=Decimal("-100"),
            currency="USD",
            base_currency="EUR",
            as_of=datetime(2026, 10, 30, tzinfo=UTC),
        )
    )
    db.add(
        InvestmentPlan(
            tenant_id=1,
            status="active",
            monthly_contribution=Decimal("300"),
            monthly_contribution_currency="EUR",
            horizon_years=10,
            start_date=date(2026, 1, 1),
            target_allocations=[{"ticker": "KO", "weight": 50}],
        )
    )
    db.commit()
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
@pytest.mark.parametrize(
    "question", ["How much have I invested?", "how much money have I invested in total?"]
)
def test_english_invested(question):
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, question)
    assert "I can't answer" not in resp.answer
    assert "650.00 €" in resp.answer


@pytest.mark.usefixtures("_en")
@pytest.mark.parametrize(
    "question", ["How much do I contribute a month?", "how much do I contribute monthly?"]
)
def test_english_contribute(question):
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "account_plan"
    assert resp.answer.startswith("Your contribution plan: 300.00 € a month")


def test_spanish_aporto():
    resp = _ask(_db(), "¿Cuánto aporto al mes?")
    assert resp.llm_trace["path"] == "account_plan"
    assert resp.answer.startswith("Tu plan de aportación: 300,00 € al mes")


def test_user_b_has_no_plan():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánto aporto al mes?")
    assert resp.answer.startswith("No tienes un plan de aportación guardado.")
