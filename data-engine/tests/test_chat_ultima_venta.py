"""Chat: «¿cuál fue mi última venta?» / «what was my last sale?» con tus ventas guardadas.

«¿cuándo fue mi última compra?» ya listaba tus operaciones, pero «¿cuál fue mi
última venta?» caía al modelo general («No tengo fuentes verificadas…») y en inglés
«what was my last sale?» también. Ahora lista solo tus ventas guardadas, la más
reciente primero. Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_cuantas_operaciones import _ask, _db, _today  # noqa: F401


@pytest.mark.parametrize("question", ["¿Cuál fue mi última venta?", "¿cuándo fue mi última venta?",
                                      "mis últimas ventas"])
def test_last_sells(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "Tus últimas ventas guardadas (la más reciente primero):",
        "- 1 mar 2026: venta de 1 KO a 10,00 USD.",
    ]


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "What was my last sale?")
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.answer.splitlines() == [
        "Your latest saved sells (most recent first):",
        "- Mar 1, 2026: sold 1 KO at 10.00 USD.",
    ]


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿cuál fue mi última venta?")
    assert resp.answer.splitlines()[1:] == ["- 8 oct 2026: venta de 1 TSLA a 10,00 USD."]


def test_no_sells():
    resp = _ask(_db(empty=True), "¿cuál fue mi última venta?")
    assert resp.answer == "No tienes ventas guardadas. Puedes importarlas en Cartera."


def test_last_buy_unchanged():
    resp = _ask(_db(), "¿cuál fue mi última compra?")
    assert resp.answer.splitlines()[0] == "Tus últimas compras y ventas guardadas (la más reciente primero):"
