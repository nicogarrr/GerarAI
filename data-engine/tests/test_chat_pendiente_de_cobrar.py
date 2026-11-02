"""Chat: «¿qué tengo pendiente de cobrar?» / «what's pending to collect?» sin la palabra dividendo.

Antes la versión inglesa caía al modelo general («I can't answer with sources…»)
y la española contestaba con los dividendos cobrados del año, no con lo que queda
por cobrar. Ahora las dos van a lo mismo que «¿qué dividendos voy a cobrar?»: lo
declarado y aún sin pagar de tus posiciones. Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_calendario_dividendos import _ask, _db


@pytest.mark.parametrize("question", ["¿Qué tengo pendiente de cobrar?", "¿Qué me queda por cobrar?",
                                      "¿cuánto tengo pendiente de cobrar?", "What's pending to collect?",
                                      "what do I have left to collect?"])
def test_pending_to_collect(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_upcoming_dividends"
    assert resp.llm_trace["provider_calls"] == 0
    assert "Total: 14,75 USD." in resp.answer
    assert "AAPL" not in resp.answer


@pytest.mark.parametrize("question", ["What's pending to collect?", "what is still to collect?"])
def test_pending_to_collect_english(question, monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_upcoming_dividends"
    assert resp.answer.startswith("Declared dividends you still have to collect")
    assert "KO" in resp.answer and "MSFT" in resp.answer and "AAPL" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "what's pending to collect?")
    assert resp.llm_trace["path"] == "account_upcoming_dividends"
    assert "AAPL" in resp.answer
    for leak in ("KO", "MSFT", "UBER"):
        assert leak not in resp.answer


def test_ticker_question_stays_on_the_company():
    resp = _ask(_db(), "¿Qué tengo pendiente de cobrar de KO?")
    assert resp.llm_trace.get("path") != "account_upcoming_dividends"
