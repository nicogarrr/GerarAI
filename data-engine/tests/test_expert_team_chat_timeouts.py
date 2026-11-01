"""Chat con el equipo de expertos: si un experto tarda, se contesta con los demás.

Antes, si un experto se pasaba del tope del chat (45 s), se perdía TODO lo
que habían contestado los otros y el chat volvía a la síntesis de siempre;
y el Cerebro listaba como «respondieron» a todos los planificados. Ahora el
equipo corre con un presupuesto por debajo del tope del chat: el lento sale
como «no respondió a tiempo», la respuesta usa lo que sí llegó y la traza
dice quién respondió y quién no (lo que pinta el Cerebro). Modelo falso.
"""

from __future__ import annotations

import asyncio

from app.services.expert_team import chat as team_chat
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    flag_on,
    synthesis_calls,
)

QUESTION = "¿Merece la pena CHAT?"


class _SlowValuation(_FakeProvider):
    async def complete(self, request):
        if "valuation" in dict(request.metadata).get("expert_team_task", ""):
            self.tasks.append("valuation:slow")
            await asyncio.sleep(5)
        return await super().complete(request)


def test_slow_expert_does_not_lose_the_others(db, synthesis_calls, flag_on, monkeypatch):
    monkeypatch.setattr(team_chat, "CHAT_TEAM_TIMEOUT_S", 1.5)
    response = _ask(db, QUESTION, _SlowValuation())
    assert response.model == "expert_team"
    trace = response.llm_trace["expert_team"]
    assert trace["timed_out"] == ["valuation"]
    assert "fundamental" in trace["answered"] and "valuation" not in trace["answered"]
    assert "**Valoración**: no respondió a tiempo." in response.answer
    assert "Fundamental" in response.answer
    assert synthesis_calls == []


def test_trace_lists_who_answered(db, synthesis_calls, flag_on):
    response = _ask(db, QUESTION, _FakeProvider())
    trace = response.llm_trace["expert_team"]
    assert trace["timed_out"] == []
    assert trace["answered"] and set(trace["answered"]) <= set(trace["plan"])


def test_team_budget_stays_under_the_chat_cap():
    assert team_chat.team_budget_s(45.0) < 45.0
    assert 0 < team_chat.team_budget_s(4.0) < 4.0
