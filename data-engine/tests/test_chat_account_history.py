"""Chat: «¿cuánto valía mi cartera hace un mes?» con las fotos diarias guardadas.

Antes una pregunta por el pasado de la cartera («hace un mes», «este mes»,
«la última semana») daba el resumen de hoy. Ahora compara la última foto diaria
con la de esa fecha, separando aportaciones/retiradas. Solo lectura, solo tu tenant.
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
        raise AssertionError("el historial no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 1))


def _snap(db, tenant, portfolio_id, day, total, flow="0", twr=None):
    db.add(PortfolioDailySnapshot(
        tenant_id=tenant, portfolio_id=portfolio_id, snapshot_date=day, base_currency="EUR",
        positions_value_base=Decimal(total), cash_value_base=Decimal("0"), total_value_base=Decimal(total),
        net_external_flow_base=Decimal(flow), daily_return=None, pricing_coverage=Decimal("1"),
        cumulative_twr=None if twr is None else Decimal(twr),
    ))


def _db(twr=False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant in (1, 2):
        db.info["tenant_id"] = tenant
        p = Portfolio(tenant_id=tenant, name="Main", base_currency="EUR", is_default=True)
        db.add(p)
        db.flush()
        if tenant == 1:
            _snap(db, 1, p.id, date(2026, 9, 30), "9000", twr="0.10" if twr else None)
            _snap(db, 1, p.id, date(2026, 10, 1), "9100", twr="0.11" if twr else None)
            _snap(db, 1, p.id, date(2026, 10, 15), "9800", flow="500", twr="0.13" if twr else None)
            _snap(db, 1, p.id, date(2026, 10, 30), "10250", twr="0.221" if twr else None)
        else:
            _snap(db, 2, p.id, date(2026, 10, 1), "555555")
            _snap(db, 2, p.id, date(2026, 10, 30), "500000")
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Cuánto valía mi cartera hace un mes?", "¿Cómo ha ido mi cartera en el último mes?",
                                      "evolución de mi cartera hace 31 días"])
def test_one_month_ago(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") == "portfolio_history"
    assert resp.answer.startswith("El 1 oct 2026 tu cartera valía 9.100,00 €; en la última foto (30 oct 2026), "
                                  "10.250,00 €: +1.150,00 €.")
    assert "Aportaciones/retiradas netas en ese tiempo: +500,00 €; sin ellas, +650,00 € (+7,1 % aprox.)." in resp.answer


def test_uses_twr_when_saved():
    resp = _ask(_db(twr=True), "¿Cuánto valía mi cartera hace un mes?")
    assert "sin ellas, +650,00 € (+10,0 % TWR)." in resp.answer


def test_this_month_without_new_snapshot():
    resp = _ask(_db(), "¿Cuánto ha subido mi cartera este mes?")
    assert resp.answer.startswith("Aún no hay ninguna foto de tu cartera de este mes")


def test_last_month_start_is_before_history():
    resp = _ask(_db(), "¿Cuánto valía mi cartera hace un año?")
    assert resp.answer.startswith("No tengo foto de tu cartera del 1 nov 2025 ni anterior: la primera es del 30 sept 2026.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánto valía mi cartera hace un mes?")
    assert "555.555,00 €" in resp.answer and "9.100" not in resp.answer
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Cuánto valía mi cartera hace un mes?")
    assert resp.answer.startswith("Aún no hay histórico diario de tu cartera")


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "How much was my portfolio worth a month ago?")
        assert resp.answer.startswith("On Oct 1, 2026 your portfolio was worth 9,100.00 €; in the latest snapshot "
                                      "(Oct 30, 2026), 10,250.00 €: +1,150.00 €.")
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["¿Cuánto ha subido mi cartera hoy?", "¿Cuánto ha subido UBER este mes?",
                                      "¿Cuánto he ganado este año?", "¿Cómo va mi cartera?"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "portfolio_history"
