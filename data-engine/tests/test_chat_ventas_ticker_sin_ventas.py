"""Chat «¿qué he vendido de UBER este año?» cuando UBER no tiene ventas ese año.

El filtro por ticker caía a TODAS las ventas del año si el ticker pedido no
tenía ninguna (``… or realized``), así que respondía «En 2026 vendiste: KO …»
como si fuera la respuesta sobre UBER. Ahora, si el ticker es una empresa
conocida, dice que no hay ventas suyas ese año; una palabra en mayúsculas que
no es ninguna empresa («OK») sigue sin filtrar, como antes.
"""

import asyncio
from datetime import date

import pytest

from app.core.config import get_settings
from app.services import brain_account_tools
from app.services.chat_service import ChatService
from tests.test_chat_account_year import _db


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las ventas del año no deben pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_ticker_without_sales_says_so():
    resp = _ask(_db(), "¿Qué he vendido de UBER este año?")
    assert resp.llm_trace["path"] == "account_sales"
    assert resp.answer.startswith("En 2026 no hay ventas de UBER en tus operaciones guardadas.")
    assert "KO" not in resp.answer


def test_ticker_without_sales_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "What did I sell of UBER this year?")
    assert resp.llm_trace["path"] == "account_sales"
    assert resp.answer.startswith("In 2026 there are no sales of UBER in your saved trades.")
    assert "KO" not in resp.answer


def test_ticker_with_sales_still_filters():
    resp = _ask(_db(), "¿Qué he vendido de KO este año?")
    assert "- KO: 20 acciones el 1 oct 2026" in resp.answer


def test_word_that_is_not_a_company_does_not_filter():
    resp = _ask(_db(), "¿Qué he vendido este año? OK")
    assert resp.llm_trace["path"] == "account_sales"
    assert "- KO: 20 acciones el 1 oct 2026" in resp.answer
