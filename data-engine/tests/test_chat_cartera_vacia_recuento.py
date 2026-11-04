"""Chat con la cartera vacía: recuento de posiciones y posición de un ticker.

Con cero posiciones abiertas, «¿cuántas posiciones tengo?», «¿qué acciones
tengo?» o «how many positions do I have?» caían al modelo general («No puedo
responderte con fuentes ahora mismo…»), y «¿cuántas acciones de AAPL tengo?» /
«¿cómo va mi posición en AAPL?» al volcado de datos de la empresa («Todavía no
tengo hechos financieros…»), como si no se hubiera preguntado por la cartera.
Ahora dicen que no hay posiciones guardadas, igual que ya hacían la
rentabilidad y el ranking. «¿Cómo va mi cartera?» sigue en el contexto personal.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401
from tests.test_chat_cartera_vacia import EMPTY, _empty_db


@pytest.mark.parametrize("question", [
    "¿cuántas posiciones tengo?",
    "¿Qué acciones tengo?",
    "¿cuántas empresas tengo?",
])
def test_recuento_con_cartera_vacia_lo_dice(question):
    resp = _ask(_empty_db(), question)
    assert resp.answer == EMPTY
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert resp.llm_trace["provider_calls"] == 0


@pytest.mark.parametrize("question", [
    "¿cuántas acciones de AAPL tengo?",
    "¿cómo va mi posición en AAPL?",
])
def test_posicion_de_un_ticker_con_cartera_vacia(question):
    resp = _ask(_empty_db(), question)
    assert resp.llm_trace["path"] == "portfolio_position"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.startswith("No tienes ninguna posición abierta en AAPL")
    assert "hechos financieros" not in resp.answer


def test_con_posiciones_no_cambia():
    db = _db()
    db.info["tenant_id"] = 1
    resp = _ask(db, "¿cuántas posiciones tengo?")
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert resp.answer != EMPTY


def test_sin_tenant_no_dice_cartera_vacia():
    db = _db()
    db.info.pop("tenant_id", None)
    try:
        resp = _ask(db, "¿cuántas posiciones tengo?")
    except AssertionError:
        return  # sin tenant no se lee cartera: sigue la ruta de siempre (modelo)
    assert resp.answer != EMPTY


@pytest.mark.parametrize("question,expected", [
    ("How many positions do I have?", "You have no saved positions in your portfolio (/portfolio)."),
    ("How many shares of AAPL do I have?", "You have no open position in AAPL"),
])
def test_english(monkeypatch, question, expected):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _empty_db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.answer.startswith(expected)
    assert resp.llm_trace["provider_calls"] == 0
