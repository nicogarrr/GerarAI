"""Chat: «¿cuánto ha subido mi cartera hoy?» responde con la variación del día.

Antes daba el resumen de posiciones sin ninguna variación diaria. La cifra sale
de la foto diaria de la cartera (portfolio_daily_snapshots): rentabilidad del
día sin aportaciones/retiradas y su importe, siempre fechada. Solo lectura y
solo la cartera del usuario que pregunta.
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


def _snap(db, tenant, portfolio_id, day, total, ret, flow="0", coverage="1"):
    db.add(PortfolioDailySnapshot(
        tenant_id=tenant, portfolio_id=portfolio_id, snapshot_date=day, base_currency="EUR",
        positions_value_base=Decimal(total), cash_value_base=Decimal("0"), total_value_base=Decimal(total),
        net_external_flow_base=Decimal(flow), daily_return=None if ret is None else Decimal(ret),
        pricing_coverage=Decimal(coverage),
    ))


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant in (1, 2):
        db.info["tenant_id"] = tenant
        p = Portfolio(tenant_id=tenant, name="Main", base_currency="EUR", is_default=True)
        db.add(p)
        db.flush()
        if tenant == 1:
            _snap(db, 1, p.id, date(2026, 10, 29), "10000", None)
            _snap(db, 1, p.id, date(2026, 10, 30), "10250", "0.025")
        else:
            _snap(db, 2, p.id, date(2026, 10, 28), "555555", None)
            _snap(db, 2, p.id, date(2026, 10, 30), "500000", "-0.10")
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


@pytest.mark.parametrize("question", [
    "¿Cuánto ha subido mi cartera hoy?",
    "¿cuánto ha bajado mi cartera hoy?",
    "¿Cómo va mi cartera hoy?",
    "¿Cuánto he ganado hoy?",
    "variación diaria de mi cartera",
])
def test_daily_change_questions(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    assert resp.answer.startswith("Hoy (30 oct 2026) tu cartera sube +2,5 % (+250,00 €)")
    assert "10.250,00 €" in resp.answer
    assert "29 oct 2026" in resp.answer
    assert resp.sources and resp.sources[0]["url"] == "/portfolio"


def test_snapshot_from_previous_day_is_dated_not_today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 2))
    resp = _ask(_db(), "¿Cuánto ha subido mi cartera hoy?")
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    assert resp.answer.startswith("Aún no hay foto de hoy de tu cartera. El último día guardado (30 oct 2026)")
    assert "+2,5 %" in resp.answer


def test_no_return_when_day_is_not_comparable():
    db = _db()
    db.query(PortfolioDailySnapshot).filter_by(snapshot_date=date(2026, 10, 30)).update(
        {"daily_return": None}
    )
    db.commit()
    resp = _ask(db, "¿Cuánto ha subido mi cartera hoy?")
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    assert "no puedo calcular la variación" in resp.answer
    assert "+250" not in resp.answer


def test_without_snapshots():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    resp = _ask(db, "¿Cuánto ha subido mi cartera hoy?")
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    assert "Aún no hay histórico diario de tu cartera" in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánto ha subido mi cartera hoy?")
    assert "500.000,00 €" in resp.answer and "-10,0 %" in resp.answer
    assert "10.250" not in resp.answer and "28 oct 2026" in resp.answer
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Cuánto ha subido mi cartera hoy?")
    assert "Aún no hay histórico diario" in resp.answer
    assert "10.250" not in resp.answer and "500.000" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "How much is my portfolio up today?")
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    assert resp.answer.startswith("Today (Oct 30, 2026) your portfolio is up +2.5% (+250.00 €)")


def test_other_questions_unchanged():
    resp = _ask(_db(), "¿Cuánto vale UBER hoy?")
    assert resp.llm_trace.get("path") != "portfolio_daily_change"
