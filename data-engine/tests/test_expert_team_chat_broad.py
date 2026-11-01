"""Chat: preguntas amplias sobre una empresa («¿merece la pena X?») van al equipo.

Antes el plan del chat solo miraba palabras de cada experto («riesgo»,
«valoración»…), así que «¿Merece la pena CHAT?» o «¿Debería comprar CHAT?»
no activaban el equipo y la segunda acababa en «No ejecuto órdenes». Con
EXPERT_TEAM_ENABLED encendido ahora las contestan fundamental, valoración y
riesgo. Con el flag apagado nada cambia, y las preguntas de tu cuenta/cartera
y las órdenes de verdad siguen por su ruta. LLM FALSO, sin red.
"""

from __future__ import annotations

import pytest

from app.services.expert_team import chat as team_chat
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    flag_on,
    synthesis_calls,
)

BROAD = ["fundamental", "valuation", "risk"]


@pytest.mark.parametrize(
    "question",
    [
        "¿Merece la pena CHAT?",
        "¿Vale la pena invertir en CHAT?",
        "¿Debería comprar CHAT a estos precios?",
        "¿Qué opinas de CHAT?",
        "Analiza CHAT",
        "¿Es CHAT una buena inversión?",
        "Is CHAT worth buying?",
        "Should I buy CHAT?",
        "What do you think about CHAT?",
        "Is CHAT a good investment?",
    ],
)
def test_broad_questions_plan_the_core_experts(question):
    assert team_chat.plan_for(question, "CHAT")[: len(BROAD)] == BROAD


@pytest.mark.parametrize(
    "question",
    ["¿Cuál es el precio de CHAT?", "¿Cuántas acciones tengo de CHAT?", "Vende mis acciones de CHAT", "hola"],
)
def test_plain_questions_do_not_plan_the_team(question):
    assert len(team_chat.plan_for(question, "CHAT")) < team_chat.MIN_EXPERTS


def test_flag_on_worth_it_question_uses_the_team(db, synthesis_calls, flag_on):
    provider = _FakeProvider()
    response = _ask(db, "¿Merece la pena CHAT?", provider)
    assert response.model == "expert_team"
    assert response.llm_trace["expert_team"]["plan"][: len(BROAD)] == BROAD
    assert synthesis_calls == []


def test_flag_on_should_i_buy_is_advice_not_an_order(db, synthesis_calls, flag_on):
    response = _ask(db, "¿Debería comprar CHAT?", _FakeProvider())
    assert response.model == "expert_team"
    assert "No ejecuto órdenes" not in response.answer


def test_flag_on_real_order_keeps_the_refusal(db, synthesis_calls, flag_on):
    provider = _FakeProvider()
    response = _ask(db, "Vende mis acciones de CHAT", provider)
    assert response.llm_trace["path"] == "order_verb"
    assert not any(task.startswith("expert_team") for task in provider.tasks)


def test_flag_off_should_i_buy_is_unchanged(db, synthesis_calls):
    provider = _FakeProvider()
    response = _ask(db, "¿Debería comprar CHAT?", provider)
    assert response.llm_trace["path"] == "order_verb"
    assert not any(task.startswith("expert_team") for task in provider.tasks)


def test_flag_on_portfolio_questions_are_not_stolen(db, synthesis_calls, flag_on):
    provider = _FakeProvider()
    for question in ("¿Qué opinas de mi cartera?", "¿Merece la pena mi cartera?"):
        response = _ask(db, question, provider, ticker=None)  # pyright: ignore[reportArgumentType]
        assert response.model != "expert_team"
    assert not any(task.startswith("expert_team") for task in provider.tasks)
