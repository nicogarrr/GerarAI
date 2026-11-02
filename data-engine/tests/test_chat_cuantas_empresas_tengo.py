"""Chat: «¿cuántas empresas tengo?» responde con tus posiciones, sin el modelo.

En inglés «how many companies do I have?» ya iba al volcado de posiciones y en
castellano «¿cuántas posiciones tengo?» también, pero «¿cuántas empresas tengo?»
caía al modelo general («No puedo responderte con fuentes…»). Solo lectura y
solo del tenant.
"""

import pytest

from tests.test_chat_que_acciones_tengo import _ask, _db


@pytest.mark.parametrize("question", ["¿Cuántas empresas tengo?", "¿cuántas empresas tengo en cartera?",
                                      "¿Cuántos valores tengo?", "cuantas compañías tengo"])
def test_how_many_companies(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.startswith("Tu cartera guardada tiene 1 posición abierta")
    assert "AAPL" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuántas empresas tengo?")
    assert "AAPL" in resp.answer and "UBER" not in resp.answer


@pytest.mark.parametrize("question", ["¿Cuántas empresas tengo en la watchlist?", "¿cuántas empresas tengo en seguimiento?"])
def test_watchlist_is_not_the_portfolio(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "portfolio_overview"
