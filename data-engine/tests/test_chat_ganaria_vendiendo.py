"""Chat: «¿cuánto ganaría vendiendo UBER?» simula la venta de tu posición.

«¿Cuánto ganaría si vendo UBER?» ya simulaba la venta (FIFO e IRPF), pero con
el gerundio («vendiendo», «al vender») la pregunta daba los datos de la empresa
(«Todavía no tengo hechos financieros fiables…»). Ahora es la misma simulación.
La venta ya hecha («¿cuánto gané vendiendo UBER?») sigue yendo a lo realizado.
"""

import pytest

from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401


@pytest.mark.parametrize("question", ["¿Cuánto ganaría vendiendo UBER?", "¿cuánto ganaría al vender UBER?",
                                      "¿cuánto IRPF pagaría vendiendo UBER?"])
def test_conditional_gerund_simulates(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.startswith("Si vendieras hoy todas tus 30 acciones de UBER")
    assert _ask(_db(), "¿cuánto ganaría si vendo UBER?").answer.split("\n")[0] == resp.answer.split("\n")[0]


def test_past_sale_unchanged():
    assert _ask(_db(), "¿cuánto gané vendiendo UBER?").llm_trace["path"] == "portfolio_realized_sale"
