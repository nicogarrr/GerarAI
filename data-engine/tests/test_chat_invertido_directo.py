"""Chat: «¿cuánto tengo invertido?» contesta con lo invertido, no con la rentabilidad.

Antes «¿cuánto tengo invertido?» o «¿cuánto he invertido en MSFT?» decían «La
rentabilidad guardada de tu cartera es +55,56 % sobre el coste de compra…»: el
coste iba dentro, pero no era la respuesta. Ahora la cifra va primero (coste de
compra guardado de las posiciones abiertas) y después lo que valen hoy. Solo
lectura, sin modelo.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401


@pytest.mark.parametrize("question", ["¿Cuánto tengo invertido?", "¿cuánto he invertido en total?",
                                      "¿Cuánto dinero tengo invertido?"])
def test_portfolio_invested(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer == (
        "Tienes invertidos 2.700,00 € en tus posiciones abiertas (coste de compra guardado); "
        "hoy valen 4.200,00 € (+55,56 %, +1.500 €), con datos a 30 oct 2026. No cuenta caja ni ventas cerradas."
    )


def test_ticker_invested():
    resp = _ask(_db(), "¿Cuánto he invertido en MSFT?")
    assert resp.answer == (
        "Tienes invertidos 1.200,00 € en MSFT (coste de compra guardado); "
        "hoy valen 1.800,00 € (+50 %, +600 €), con datos a 30 oct 2026. No cuenta caja ni ventas cerradas."
    )


def test_return_question_unchanged():
    resp = _ask(_db(), "¿Cuál es mi rentabilidad?")
    assert resp.answer.startswith("La rentabilidad guardada de tu cartera es +55,56 %")


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How much have I invested?")
    finally:
        get_settings.cache_clear()
    assert resp.answer == (
        "You have 2,700.00 € invested in your open positions (saved purchase cost); "
        "today it is worth 4,200.00 € (+55.56%, +1,500.00 €), as of Oct 30, 2026. "
        "Cash and closed sales are not included."
    )


def test_tenant_isolation():
    db = _db()
    db.info["tenant_id"] = 2
    assert "2.700,00" not in _ask(db, "¿Cuánto tengo invertido?").answer
