"""Chat con el equipo de expertos: más formas de preguntar (español e inglés).

Solo palabras/regex, sin llamadas extra al modelo. Preguntas amplias como
«¿tiene futuro X?», «pros y contras de X», «¿comprarías X?», «is X a buy?»
o «bull and bear case for X» planifican a fundamental, valoración y riesgo;
«¿está sobrevalorada X?» o «¿es muy arriesgada X?» llaman a su experto.
Las preguntas de cuenta/cartera del Cerebro (cuánto gané, si vendo cuánto
pago, cuántas tengo, cuánto subió hoy, órdenes) no entran en el equipo.
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
        "¿Tiene futuro CHAT?",
        "Pros y contras de CHAT",
        "Puntos fuertes y débiles de CHAT",
        "¿Comprarías CHAT ahora?",
        "¿Entrarías en CHAT?",
        "¿Es buen momento para comprar CHAT?",
        "¿Me recomiendas CHAT?",
        "Dame tu opinión sobre CHAT",
        "¿Cuáles son las perspectivas de CHAT?",
        "¿CHAT es un buen negocio?",
        "Is CHAT a buy?",
        "Would you buy CHAT?",
        "Do you recommend CHAT?",
        "Pros and cons of CHAT",
        "Bull and bear case for CHAT",
        "What's the outlook for CHAT?",
        "Long-term prospects of CHAT",
        "Give me a deep dive on CHAT",
    ],
)
def test_more_broad_phrasings_plan_the_core_experts(question):
    assert team_chat.plan_for(question, "CHAT")[: len(BROAD)] == BROAD


@pytest.mark.parametrize(
    ("question", "expert"),
    [
        ("¿Está sobrevalorada CHAT?", "valuation"),
        ("¿CHAT está infravalorada?", "valuation"),
        ("Is CHAT overvalued?", "valuation"),
        ("Is CHAT undervalued?", "valuation"),
        ("¿Es muy arriesgada CHAT?", "risk"),
        ("¿CHAT es volátil?", "risk"),
    ],
)
def test_specific_phrasings_call_their_expert(question, expert):
    assert expert in team_chat.plan_for(question, "CHAT")


def test_two_specific_phrasings_use_the_team():
    assert team_chat.plan_for("¿Está sobrevalorada CHAT y es muy arriesgada?", "CHAT") == ["valuation", "risk"]


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuánto he ganado con CHAT?",
        "Si vendo 10 CHAT, ¿cuánto pagaría a Hacienda?",
        "¿A cuánto compré CHAT?",
        "¿Cuántas acciones tengo de CHAT?",
        "¿Cuánto ha subido CHAT hoy?",
        "Vende mis acciones de CHAT",
        "Compra 10 CHAT",
        "¿Qué dividendos me ha pagado CHAT?",
        "How much did I make on CHAT?",
        "Sell my CHAT shares",
    ],
)
def test_cerebro_account_questions_are_not_stolen(question):
    assert len(team_chat.plan_for(question, "CHAT")) < team_chat.MIN_EXPERTS


def test_flag_on_new_phrasing_uses_the_team(db, synthesis_calls, flag_on):
    provider = _FakeProvider()
    response = _ask(db, "¿Tiene futuro CHAT?", provider)
    assert response.model == "expert_team"
    assert response.llm_trace["expert_team"]["plan"][: len(BROAD)] == BROAD
    assert synthesis_calls == []
