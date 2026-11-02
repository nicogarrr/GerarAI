"""Chat: «mis 2000 acciones» no es el año 2000.

El año de la pregunta se tomaba del primer número 19xx/20xx que apareciera,
así que una cantidad («con mis 2000 acciones», «2025 euros») se leía como el
año pedido: «¿cuánto he ganado este año con mis 2000 acciones?» respondía del
año 2000 (o no respondía), y los dividendos de la cartera buscaban los del
año 2000. Ahora un número seguido de acciones, títulos, euros, dólares o
shares es una cantidad, no un año.
"""

import asyncio
from datetime import UTC, date, datetime

import pytest

from app.core.config import get_settings
from app.services import brain_account_tools
from app.services.chat_service import ChatService
from tests.test_chat_account_year import _db
from tests.test_chat_dividends_year import db as dividends_db  # noqa: F401 - fixture

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", [
    "¿Cuánto he ganado este año con mis 2000 acciones?",
    "¿Cuánto he ganado este año con mis 2025 euros invertidos?",
])
def test_quantity_is_not_the_year_for_gains(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_year_gains"
    assert "2026" in resp.answer
    assert "2000" not in resp.answer and "2025 " not in resp.answer


def test_quantity_is_not_the_year_for_sales():
    resp = _ask(_db(), "¿Qué he vendido este año de mis 2000 acciones?")
    assert resp.llm_trace["path"] == "account_sales"
    assert resp.answer.startswith("En 2026 vendiste:")


def test_explicit_year_still_wins():
    resp = _ask(_db(), "¿Qué vendí en 2025 de mis 2000 acciones?")
    assert resp.llm_trace["path"] == "account_sales"
    assert "- UBER: 10 acciones el 1 jun 2025" in resp.answer


@pytest.mark.parametrize("question", [
    "¿Cuántos dividendos he cobrado este año con mis 2000 acciones?",
    "¿Qué dividendos cobra mi cartera con mis 2010 títulos?",
])
def test_dividends_quantity_is_not_the_year(dividends_db, question):  # noqa: F811
    from app.services.brain_data_tools import _dividend_answer

    response = _dividend_answer(dividends_db, question, 1)
    assert response is not None
    assert "1 pago(s) en 2026" in response.answer


def test_dividends_explicit_year_still_wins(dividends_db):  # noqa: F811
    from app.services.brain_data_tools import _dividend_answer

    response = _dividend_answer(dividends_db, "¿Cuántos dividendos cobré en 2025 con mis 2000 acciones?", 1)
    assert response is not None
    assert "2 pago(s) en 2025" in response.answer
