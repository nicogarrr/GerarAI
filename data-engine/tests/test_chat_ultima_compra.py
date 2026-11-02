"""Chat: «¿cuál fue mi última compra?», «¿qué he comprado este año?» listan solo compras.

Antes, cualquier pregunta por tus compras listaba también las ventas («Tus
últimas compras y ventas guardadas…» con la venta de KO de marzo debajo de la
pregunta por la compra). Las ventas ya tenían su lista propia (#4347).
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_cuantas_operaciones import _ask, _db, _today  # noqa: F401


@pytest.mark.parametrize("question", ["¿Cuál fue mi última compra?", "mis últimas compras"])
def test_last_buys_only(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.answer.splitlines() == [
        "Tus últimas compras guardadas (la más reciente primero):",
        "- 5 oct 2026: compra de 1 KO a 10,00 USD.",
        "- 12 sept 2026: compra de 1 ITX a 10,00 USD.",
        "- 1 jun 2025: compra de 1 KO a 10,00 USD.",
    ]


def test_buys_of_a_period():
    resp = _ask(_db(), "¿Qué he comprado este año?")
    assert resp.answer.splitlines()[0] == "Tus compras guardadas de 2026:"
    assert "venta" not in resp.answer


def test_no_buys():
    resp = _ask(_db(empty=True), "¿cuál fue mi última compra?")
    assert resp.answer == "No tienes compras guardadas. Puedes importarlas en Cartera."


def test_trades_keep_buys_and_sells():
    resp = _ask(_db(), "mis últimas operaciones")
    assert "venta de 1 KO" in resp.answer and "compra de 1 KO" in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "What was my last purchase?")
    finally:
        get_settings.cache_clear()
    assert resp.answer.splitlines()[0] == "Your latest saved buys (most recent first):"
    assert "sold" not in resp.answer
