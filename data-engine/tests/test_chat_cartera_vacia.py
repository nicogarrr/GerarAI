"""Chat con la cartera vacía: se dice, sin modelo.

Con cero posiciones abiertas, «¿cuál es mi rentabilidad?», «¿cuánto tengo
invertido?», «¿cuál es mi posición más grande?»
o «¿cuánto pierdo?» caían al modelo general («No tengo fuentes verificadas en
esta ruta…» o «No puedo responderte con fuentes ahora mismo…»), que podía
inventar una cartera. Ahora contestan que no hay posiciones guardadas, con el
mismo texto que ya daba el contexto personal.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401

EMPTY = ("No tienes posiciones guardadas en la cartera (/portfolio). Importa el CSV de IBKR o añade "
         "las posiciones y te digo cómo va, con peso, P&L y nivel DCA de cada una.")


def _empty_db():
    db = _db()
    db.info["tenant_id"] = 2  # vendió todo AAPL: sin posiciones abiertas
    return db


@pytest.mark.parametrize("question", ["¿Cuál es mi rentabilidad?", "¿cuánto tengo invertido?",
                                      "¿cuál es mi posición más grande?", "¿cuánto pierdo?"])
def test_empty_portfolio_says_so(question):
    resp = _ask(_empty_db(), question)
    assert resp.answer == EMPTY
    assert resp.llm_trace["provider_calls"] == 0


def test_closed_ticker_and_year_unchanged():
    db = _empty_db()
    assert _ask(db, "¿cuánto gané con AAPL?").answer.startswith("Ya no tienes posición abierta en AAPL.")
    assert _ask(_empty_db(), "¿cuánto he ganado este año?").llm_trace["path"] == "account_year_gains"


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _empty_db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "What is my return?")
    finally:
        get_settings.cache_clear()
    assert resp.answer.startswith("You have no saved positions in your portfolio (/portfolio).")
