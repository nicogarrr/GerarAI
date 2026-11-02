"""Chat: «¿cuál es mi rentabilidad este año?» avisa de que la cifra es desde la compra.

La rentabilidad guardada es valor frente a coste de las posiciones abiertas,
desde la compra. Preguntada «este año» / «this year» se daba igual, sin decir que
no es la del año (no hay rentabilidad del año calculada sin los flujos de caja).
Ahora lo dice en una frase, como ya hace «¿cuánto he ganado este año?». La
cifra no cambia. Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_que_acciones_tengo import _ask, _db


@pytest.mark.parametrize("question", ["¿Cuál es mi rentabilidad este año?", "¿qué rentabilidad llevo en 2026?",
                                      "¿cuál es mi rentabilidad en lo que va de año?"])
def test_year_question_says_it_is_since_purchase(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.endswith(" Es desde la compra, no la de un año: la rentabilidad por año no está calculada.")


def test_plain_question_unchanged():
    resp = _ask(_db(), "¿Cuál es mi rentabilidad?")
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert "no la de un año" not in resp.answer


@pytest.mark.parametrize("question", ["What's my return this year?", "what is my return year to date?"])
def test_english(monkeypatch, question):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert resp.answer.endswith(" It is since purchase, not for a single year: the return by year is not calculated.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuál es mi rentabilidad este año?")
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert "AAPL" in str(resp.sources) and "UBER" not in str(resp.sources)
