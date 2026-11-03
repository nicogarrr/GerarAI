"""Con el equipo de expertos apagado (por defecto), pedir opinión no es dar una orden.

Prueba real del chat (2026-11-02): «¿Es buen momento para comprar más
Microsoft según las señales DCA?» contestaba «No ejecuto órdenes: GerarAI no
compra ni vende en tu bróker». Las órdenes de verdad («compra 10 acciones
de X», «vende mis acciones de X») siguen con esa respuesta.
"""

from __future__ import annotations

import pytest

from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    synthesis_calls,
)


@pytest.mark.parametrize(
    "question",
    [
        "¿Es buen momento para comprar más CHAT según las señales DCA?",
        "¿Debería vender CHAT? Ha subido mucho",
        "¿Me conviene comprar CHAT ahora?",
        "Should I buy more CHAT?",
    ],
)
def test_pedir_opinion_no_es_una_orden(db, question):
    response = _ask(db, question, _FakeProvider())
    assert (response.llm_trace or {}).get("path") != "order_verb"
    assert "No ejecuto órdenes" not in response.answer


@pytest.mark.parametrize("question", ["Compra 10 acciones de CHAT", "Vende mis acciones de CHAT"])
def test_las_ordenes_siguen_sin_ejecutarse(db, question):
    response = _ask(db, question, _FakeProvider())
    assert (response.llm_trace or {}).get("path") == "order_verb"
