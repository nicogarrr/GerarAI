"""«¿Vendo X o la mantengo?» llega al equipo de expertos cuando está encendido.

Prueba real 2026-11-03 (equipo encendido solo en local): «¿Vendo Uber o la
mantengo?» iba a la síntesis normal y no a los expertos, aunque «¿debería
vender Uber?» sí entraba. Con el equipo apagado (defecto en producción) nada
cambia.
"""

from __future__ import annotations

import pytest

from app.services.expert_team import chat as team_chat
from app.services.expert_team.coordinator import is_broad_question
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    flag_on,
    synthesis_calls,
)

BROAD = ["fundamental", "valuation", "risk"]
SELL_OR_HOLD = [
    "¿Vendo CHAT o la mantengo?",
    "¿Compro más CHAT o espero?",
    "¿Mantengo CHAT o la vendo?",
    "CHAT: ¿vendo o no?",
    "Should I sell or hold CHAT?",
    "CHAT, buy or wait?",
]


@pytest.mark.parametrize("question", SELL_OR_HOLD)
def test_sell_or_hold_is_a_broad_question(question):
    assert is_broad_question(question)
    assert team_chat.plan_for(question, "CHAT")[: len(BROAD)] == BROAD


@pytest.mark.parametrize("question", ["vendo 10 CHAT", "¿Cuánto IRPF pago si vendo CHAT?", "¿Cuándo compré CHAT?"])
def test_orders_and_account_questions_are_not(question):
    assert not is_broad_question(question)


def test_flag_on_sell_or_hold_uses_the_team(db, synthesis_calls, flag_on):
    response = _ask(db, "¿Vendo CHAT o la mantengo?", _FakeProvider())
    assert response.model == "expert_team"
    assert synthesis_calls == []
