"""Chat: «how much did I make today?» y «¿cuánto gané hoy?» dan la variación del día.

En inglés «how much did I make today?» / «did I lose money today?» contestaban
con la rentabilidad desde la compra (portfolio_performance), no con el día; en
castellano «¿cuánto gané hoy?» / «¿cuánto perdí hoy?» caían igual. «¿Cuánto he
ganado hoy?» ya iba bien. Solo lectura y solo la cartera del que pregunta.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Portfolio, PortfolioDailySnapshot
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el cambio del día no debe pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant, rows in (
        (1, (("10000", None), ("10250", "0.025"))),
        (2, (("555555", None), ("500000", "-0.10"))),
    ):
        db.info["tenant_id"] = tenant
        p = Portfolio(tenant_id=tenant, name="Main", base_currency="EUR", is_default=True)
        db.add(p)
        db.flush()
        for day, (total, ret) in zip((date(2026, 10, 29), date(2026, 10, 30)), rows, strict=True):
            db.add(
                PortfolioDailySnapshot(
                    tenant_id=tenant,
                    portfolio_id=p.id,
                    snapshot_date=day,
                    base_currency="EUR",
                    positions_value_base=Decimal(total),
                    cash_value_base=Decimal("0"),
                    total_value_base=Decimal(total),
                    net_external_flow_base=Decimal("0"),
                    daily_return=None if ret is None else Decimal(ret),
                    pricing_coverage=Decimal("1"),
                )
            )
        db.commit()
    db.info["tenant_id"] = 1
    return db


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Cuánto gané hoy?", "¿cuánto perdí hoy?", "¿Cuánto he ganado hoy?"])
def test_spanish(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    assert resp.answer.startswith("Hoy (30 oct 2026) tu cartera sube +2,5 % (+250,00 €)")


@pytest.mark.parametrize(
    "question",
    [
        "How much did I make today?",
        "did I lose money today?",
        "How much have I made today?",
        "what did I earn today?",
    ],
)
def test_english(monkeypatch, question):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    assert "+2.5%" in resp.answer and "since purchase" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánto perdí hoy?")
    assert "-10,0 %" in resp.answer
    assert "10.250" not in resp.answer


def test_company_move_today_is_not_my_portfolio():
    resp = _ask(_db(), "¿Cuánto ha subido UBER hoy?")
    assert (resp.llm_trace or {}).get("path") != "portfolio_daily_change"
