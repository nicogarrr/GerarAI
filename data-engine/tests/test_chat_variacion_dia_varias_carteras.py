"""Chat «¿cuánto ha subido mi cartera hoy?» con varias carteras.

Se tomaba la foto más reciente de CUALQUIER cartera del usuario y se describía
como «tu cartera»: con dos carteras, la otra no aparecía y la cifra parecía la
de todo el patrimonio. Ahora, con varias carteras, cada una sale por separado
con su nombre; con una sola, la respuesta no cambia.
"""

import asyncio
from datetime import date

import pytest

from app.core.config import get_settings
from app.models.entities import Portfolio
from app.services import brain_account_tools
from app.services.chat_service import ChatService
from tests.test_chat_daily_change import _db, _snap


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el cambio del día no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
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
    _snap(db, 1, second.id, date(2026, 10, 29), "4000", None)
    _snap(db, 1, second.id, date(2026, 10, 30), "3960", "-0.01")
    db.commit()
    return db


def test_each_portfolio_is_described():
    resp = _ask(_two_portfolios(), "¿Cuánto ha subido mi cartera hoy?")
    assert resp.llm_trace["path"] == "portfolio_daily_change"
    text = resp.answer
    assert text.startswith("Tienes 2 carteras con foto diaria; cada una por separado:")
    assert "- «Main»: Hoy (30 oct 2026) tu cartera sube +2,5 % (+250,00 €)" in text
    assert "- «Fondos»: Hoy (30 oct 2026) tu cartera baja -1,0 % (-40,00 €)" in text
    assert len(resp.sources) == 2
    assert "555.555" not in text and "500.000" not in text  # nunca la del usuario 2


def test_each_portfolio_is_described_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _two_portfolios()
    db.info["language"] = "en"
    resp = _ask(db, "How did my portfolio do today?")
    assert resp.answer.startswith("You have 2 portfolios with a daily snapshot; each one separately:")
    assert "- «Main»: Today (Oct 30, 2026) your portfolio is up" in resp.answer
    assert "- «Fondos»: Today (Oct 30, 2026) your portfolio is down" in resp.answer


def test_single_portfolio_unchanged():
    resp = _ask(_db(), "¿Cuánto ha subido mi cartera hoy?")
    assert resp.answer.startswith("Hoy (30 oct 2026) tu cartera sube +2,5 % (+250,00 €)")
    assert len(resp.sources) == 1
