"""Chat «¿cuánto valía mi cartera hace un mes?» con varias carteras.

La comparación tomaba la foto más reciente de CUALQUIER cartera del usuario y
solo comparaba esa cartera, como si fuera todo: con dos carteras, la otra no
aparecía. Ahora, con varias carteras, cada una sale por separado con su
nombre; con una sola, la respuesta no cambia.
"""

import asyncio
from datetime import date

import pytest

from app.core.config import get_settings
from app.models.entities import Portfolio
from app.services import brain_account_tools
from app.services.chat_service import ChatService
from tests.test_chat_account_history import _db, _snap


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el historial no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 1))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def _two_portfolios():
    db = _db()
    second = Portfolio(tenant_id=1, name="Fondos", base_currency="EUR", is_default=False)
    db.add(second)
    db.flush()
    _snap(db, 1, second.id, date(2026, 10, 1), "4000")
    _snap(db, 1, second.id, date(2026, 10, 29), "3800")
    db.commit()
    return db


def test_each_portfolio_is_compared():
    resp = _ask(_two_portfolios(), "¿Cuánto valía mi cartera hace un mes?")
    assert resp.llm_trace["path"] == "portfolio_history"
    text = resp.answer
    assert text.startswith("Tienes 2 carteras con fotos diarias; cada una por separado:")
    assert "- «Main»: El 1 oct 2026 tu cartera valía 9.100,00 €; en la última foto (30 oct 2026), 10.250,00 €" in text
    assert "- «Fondos»: El 1 oct 2026 tu cartera valía 4.000,00 €; en la última foto (29 oct 2026), 3.800,00 €: -200,00 €." in text
    assert len(resp.sources) == 2
    assert "555.555" not in text and "500.000" not in text  # nunca la del usuario 2


def test_each_portfolio_is_compared_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _two_portfolios()
    db.info["language"] = "en"
    resp = _ask(db, "How much was my portfolio worth a month ago?")
    assert resp.answer.startswith("You have 2 portfolios with daily snapshots; each one separately:")
    assert "- «Fondos»: On Oct 1, 2026 your portfolio was worth 4,000.00 €" in resp.answer


def test_single_portfolio_unchanged():
    resp = _ask(_db(), "¿Cuánto valía mi cartera hace un mes?")
    assert resp.answer.startswith("El 1 oct 2026 tu cartera valía 9.100,00 €; en la última foto (30 oct 2026), "
                                  "10.250,00 €: +1.150,00 €.")
    assert "\n" in resp.answer and len(resp.sources) == 1
