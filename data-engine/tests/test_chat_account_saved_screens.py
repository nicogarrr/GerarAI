"""Chat: «¿qué pantallas tengo guardadas en el screener?» lista tus pantallas.

Antes la pregunta acababa en la respuesta general. Ahora lista tus pantallas
guardadas activas con sus criterios y las empresas que las cumplen ahora.
Solo lectura y solo tu tenant.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, SavedScreen, SavedScreenMatch
from app.services.chat_service import ChatService

_WHEN = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las pantallas no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("MSFT", "KO", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    screens = {1: (("Calidad barata", 3, True, ("MSFT", "KO")), ("Pausada", 1, False, ("AAPL",)),
                   ("Sin resultados", 2, True, ())),
               2: (("Secreta de B", 1, True, ("AAPL",)),)}
    for tenant, rows in screens.items():
        db.info["tenant_id"] = tenant
        for name, n_criteria, active, matches in rows:
            screen = SavedScreen(tenant_id=tenant, name=name, active=active, last_run_at=_WHEN,
                                 criteria=[{"left": "pe", "operator": "<", "right": "20"}] * n_criteria)
            db.add(screen)
            db.flush()
            for ticker in matches:
                db.add(SavedScreenMatch(tenant_id=tenant, saved_screen_id=screen.id, company_id=ids[ticker],
                                        first_matched_at=_WHEN, last_matched_at=_WHEN, active=True))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué pantallas tengo guardadas en el screener?", "mis pantallas del screener",
                                      "mis screeners guardados"])
def test_lists_saved_screens(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") == "account_saved_screens"
    assert resp.answer.startswith("Tienes 2 pantallas guardadas en el screener:")
    assert "- «Calidad barata»: 3 criterios; la cumplen ahora 2 empresas (MSFT, KO); última ejecución el 30 oct 2026." in resp.answer
    assert "- «Sin resultados»: 2 criterios; ninguna empresa la cumple ahora" in resp.answer
    assert "Pausada" not in resp.answer
    assert resp.answer.endswith("Para verlas o cambiarlas, ve a Screeners.")


def test_no_screens():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "mis pantallas del screener")
    assert resp.answer.startswith("No tienes pantallas guardadas en el screener. Puedes crearlas en Screeners.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "mis pantallas del screener")
    assert "«Secreta de B»" in resp.answer and "Calidad barata" not in resp.answer and "MSFT" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "What are my saved screens?")
        assert resp.answer.startswith("You have 2 saved screens:")
        assert "- «Calidad barata»: 3 criteria; 2 companies match now (MSFT, KO); last run Oct 30, 2026." in resp.answer
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["¿Qué es un screener?", "¿Pasa MSFT el screener de calidad?", "mis alertas"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_saved_screens"
