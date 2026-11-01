"""Chat: el experto fiscal entra en «¿merece la pena mantener/vender X?» si tienes la posición.

Antes solo entraba si la pregunta decía «IRPF», «impuesto», «fiscal»… Así
«¿Debería vender CHAT?» o «¿Merece la pena mantener CHAT?» (con acciones de
CHAT en cartera) se contestaban sin decir qué pasaría con Hacienda. Ahora,
en esas preguntas de mantener/vender, entra el fiscal (tu posición y los
tramos del IRPF del ahorro). Sin posición, o en «¿merece la pena comprar
X?», no entra. Detrás de EXPERT_TEAM_ENABLED; LLM FALSO, sin red.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models.entities import Company, Position
from app.services.expert_team.coordinator import ExpertTeam
from app.services.expert_team.models import RunContext, ToolSpec
from app.services.expert_team.roster import default_experts
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    flag_on,
    synthesis_calls,
)


def _plan(question: str, *, holds: bool) -> list[str]:
    experts = default_experts()

    def no_tool(_ctx: RunContext) -> list[Any]:  # pragma: no cover - plan() no lee datos
        raise AssertionError

    async def never(*_a: Any) -> str:  # pragma: no cover - plan() no razona
        raise AssertionError

    tools = {name: ToolSpec(name, no_tool) for spec in experts for name in spec.tools}
    ctx = RunContext(tenant_id=1, ticker="CHAT", question=question, mode="chat", holds_position=holds)
    return ExpertTeam(experts, tools, never).plan(ctx)


@pytest.mark.parametrize(
    "question",
    [
        "¿Merece la pena mantener CHAT?",
        "¿Debería vender CHAT?",
        "¿Debería quedarme con CHAT o salir?",
        "Should I sell CHAT?",
        "Should I keep CHAT?",
    ],
)
def test_tax_joins_hold_or_sell_questions_with_a_position(question):
    assert "tax" in _plan(question, holds=True)


@pytest.mark.parametrize("question", ["¿Merece la pena mantener CHAT?", "¿Debería vender CHAT?", "Should I sell CHAT?"])
def test_without_a_position_tax_stays_out(question):
    assert "tax" not in _plan(question, holds=False)


@pytest.mark.parametrize("question", ["¿Merece la pena CHAT?", "¿Debería comprar CHAT?", "Is CHAT worth buying?"])
def test_buy_questions_do_not_call_tax_even_with_a_position(question):
    assert "tax" not in _plan(question, holds=True)


def test_explicit_tax_words_still_call_tax_without_a_position():
    assert "tax" in _plan("¿Qué riesgo tiene CHAT y cómo tributa el dividendo?", holds=False)


def test_thesis_mode_unchanged():
    experts = default_experts()
    tools = {name: ToolSpec(name, lambda _c: []) for spec in experts for name in spec.tools}

    async def never(*_a: Any) -> str:  # pragma: no cover
        raise AssertionError

    team = ExpertTeam(experts, tools, never)
    assert "tax" not in team.plan(RunContext(tenant_id=1, ticker="CHAT", mode="thesis", holds_position=False))
    assert "tax" in team.plan(RunContext(tenant_id=1, ticker="CHAT", mode="thesis", holds_position=True))


def test_flag_on_should_i_sell_with_position_asks_tax(db, synthesis_calls, flag_on):
    company = db.query(Company).filter(Company.ticker == "CHAT").one()
    db.add(Position(tenant_id=1, company_id=company.id, quantity=10, average_cost=100, currency="USD"))
    db.commit()
    response = _ask(db, "¿Debería vender CHAT?", _FakeProvider())
    assert response.model == "expert_team"
    assert "tax" in response.llm_trace["expert_team"]["plan"]
