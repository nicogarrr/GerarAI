"""Chat: «¿cuándo presentan resultados mis empresas?» da las fechas de tus posiciones.

Antes «próximos resultados de mi cartera» devolvía el resumen de la cartera (sin
fechas) y «¿cuándo presentan resultados mis empresas?» iba al modelo general,
aunque el calendario guardado (earnings_dates) ya tenía las fechas. Solo
lectura, sin proveedores y solo con las posiciones del tenant.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.local_date import local_today
from app.models.entities import Base, Company, EarningsDate, Position
from app.services.chat_service import ChatService
from app.services.display_es import fecha_es

TODAY = local_today()


def _en(day: date) -> str:
    return f"{day.strftime('%b')} {day.day}, {day.year}"


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las fechas de resultados no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("UBER", "KO", "MSFT", "ASTS", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    holdings = {1: ("UBER", "KO", "MSFT", "ASTS"), 2: ("AAPL",)}
    for tenant, tickers in holdings.items():
        db.info["tenant_id"] = tenant
        for ticker in tickers:
            db.add(Position(tenant_id=tenant, company_id=ids[ticker], quantity=Decimal("10"),
                            average_cost=Decimal("10"), currency="USD", as_of=TODAY))
        db.commit()
    fresh = datetime.now(UTC)
    for ticker, day, session, confirmed in (
        ("UBER", TODAY + timedelta(days=3), "pre_market", False),
        ("KO", TODAY + timedelta(days=8), None, True),
        ("MSFT", TODAY + timedelta(days=120), "after_market", True),
        ("AAPL", TODAY + timedelta(days=5), "after_market", True),
        ("UBER", TODAY - timedelta(days=90), "pre_market", True),
    ):
        db.add(EarningsDate(ticker=ticker, event_date=day, session=session, confirmed=confirmed,
                            source="nasdaq", source_label="Nasdaq", fetched_at=fresh))
    db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", [
    "¿Cuándo presentan resultados mis empresas?",
    "próximos resultados de mi cartera",
    "calendario de resultados de mis posiciones",
    "¿Qué día publican resultados mis acciones?",
])
def test_upcoming_results_of_holdings(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_upcoming_earnings"
    assert resp.llm_trace["provider_calls"] == 0
    end = TODAY + timedelta(days=90)
    assert resp.answer.startswith(f"Próximos resultados de tus posiciones (hasta el {fecha_es(end)}):")
    assert f"- UBER: {fecha_es(TODAY + timedelta(days=3))}, antes de la apertura (fecha estimada)" in resp.answer
    assert f"- KO: {fecha_es(TODAY + timedelta(days=8))} (fecha confirmada)" in resp.answer
    # Orden por fecha; sin fecha en el plazo, nombradas aparte.
    assert resp.answer.index("UBER:") < resp.answer.index("KO:")
    assert "Sin fecha en ese plazo: ASTS, MSFT." in resp.answer
    assert "AAPL" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuándo presentan resultados mis empresas?")
    assert f"- AAPL: {fecha_es(TODAY + timedelta(days=5))}, tras el cierre (fecha confirmada)" in resp.answer
    assert "UBER" not in resp.answer and "KO" not in resp.answer


def test_no_positions():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "próximos resultados de mi cartera")
    assert resp.answer.startswith("No tienes posiciones abiertas")


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        for question in ("When do my holdings report earnings?", "upcoming earnings for my portfolio"):
            resp = _ask(db, question)
            assert resp.llm_trace["path"] == "account_upcoming_earnings"
            end = _en(TODAY + timedelta(days=90))
            assert resp.answer.startswith(f"Upcoming earnings for your holdings (through {end}):")
            assert f"- UBER: {_en(TODAY + timedelta(days=3))}, before the open (estimated date)" in resp.answer
            assert "No date in that window: ASTS, MSFT." in resp.answer
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", [
    "¿Cuándo presenta resultados UBER?",
    "¿qué resultados ha tenido mi cartera este año?",
    "resultados de UBER del último trimestre",
])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_upcoming_earnings"
