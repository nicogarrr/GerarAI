"""Chat: «how many shares do I have?» / «¿cuántas acciones tengo?» sin ticker.

Antes, sin ticker, la pregunta caía al modelo general («No puedo responderte con
fuentes…») aunque el volcado de posiciones ya da las acciones de cada una
(«UBER: 30 acciones…»). Ahora va a ese volcado. Con ticker sigue igual (la
posición de esa empresa). Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_que_acciones_tengo import _ask, _db


@pytest.mark.parametrize("question", ["¿Cuántas acciones tengo?", "cuantas acciones tengo en total",
                                      "¿Cuántas acciones tengo en cartera?", "How many shares do I have?",
                                      "how many shares do I own in total?"])
def test_shares_without_ticker_lists_each_holding(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert resp.llm_trace["provider_calls"] == 0
    assert "- UBER: 30 acciones" in resp.answer
    assert "AAPL" not in resp.answer


def test_english_language(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How many shares do I have?")
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert "- UBER: 30 shares" in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "how many shares do I have?")
    assert "- AAPL: 30 acciones" in resp.answer and "UBER" not in resp.answer


@pytest.mark.parametrize("question", ["How many shares of UBER do I have?", "how many shares does Apple have?",
                                      "¿Cuántas acciones tiene Apple?"])
def test_other_share_questions_are_not_the_overview(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "portfolio_overview"
