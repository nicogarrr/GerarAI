"""Chat: «¿cuánto gané con la venta de UBER?» habla de la venta ya hecha.

Prueba real del 2 nov (cerebro-real-1, caso A19): «¿cuánto gané con la venta de
Inditex de mayo 2025?» simulaba vender HOY la posición (ruta de IRPF) y
«¿cuánto gané vendiendo UBER?» daba los datos de la empresa. Ahora es lo
realizado con tus ventas guardadas de esa empresa, con el mismo FIFO en euros
del informe fiscal; un año en la pregunta acota el ejercicio. Las preguntas
hipotéticas («¿cuánto IRPF pagaría si vendo UBER?») no cambian.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401

UBER = ("Realizado con tus ventas guardadas de UBER: +268,88 € "
        "(1 venta: 1 jun 2025; en euros, FIFO como en el informe fiscal).")


@pytest.mark.parametrize("question", ["¿Cuánto gané con la venta de UBER?", "¿cuánto gané vendiendo UBER?",
                                      "¿cuánto he ganado al vender UBER?", "¿Cuánto gané con la venta de Uber Inc?"])
def test_past_sale(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_realized_sale"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer == UBER


def test_with_a_year_and_without_sales():
    assert _ask(_db(), "¿cuánto gané con la venta de UBER de junio de 2025?").answer == UBER.replace(
        "Realizado con", "Realizado en 2025 con")
    assert _ask(_db(), "¿cuánto gané con la venta de UBER en 2026?").answer == (
        "En 2026 no hay ventas de UBER en tus operaciones guardadas.")
    assert _ask(_db(), "¿cuánto gané con la venta de MSFT?").answer == "No tienes ventas guardadas de MSFT."


def test_hypothetical_still_simulates():
    resp = _ask(_db(), "¿Cuánto IRPF pagaría si vendo UBER?")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"


def test_tenant_isolation():
    db = _db()
    db.info["tenant_id"] = 2
    assert "268,88" not in _ask(db, "¿cuánto gané con la venta de UBER?").answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How much did I make selling UBER?")
    finally:
        get_settings.cache_clear()
    assert resp.answer == ("Realized with your saved sales of UBER: +268.88 € "
                           "(1 sale: Jun 1, 2025; in euros, FIFO as in the tax report).")
