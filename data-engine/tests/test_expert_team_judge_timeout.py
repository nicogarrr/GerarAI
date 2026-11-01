"""El juez del equipo de expertos tiene su propio tope.

Antes, el juez (decide cuando un experto lo ve a favor y otro en contra)
corría sin tope dentro de los últimos segundos del chat: si tardaba, vencía
el tope del chat y se perdía la respuesta ENTERA (el chat volvía a la síntesis
de siempre). Ahora el juez tiene su tope: si no llega, se contesta con lo
que dijeron los expertos, sin veredicto, y se dice que el juez no llegó.
Modelo falso, sin red.
"""

from __future__ import annotations

import asyncio
import json
import time

from app.llm import LLMResponse, Message, Usage
from app.services.expert_team import ExpertTeam, RunContext
from app.services.expert_team import chat as team_chat
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    flag_on,
    synthesis_calls,
)
from tests.test_expert_team_core import TOOLS, _citing_reasoner, _experts

QUESTION = "¿Merece la pena CHAT?"


def _split_reasoner(judge_delay: float):
    async def reason(system, user, max_tokens, task):
        if task == "expert_team.judge":
            await asyncio.sleep(judge_delay)
            return "VEREDICTO: bearish | la deuda pesa más"
        stance = "positive" if task == "expert_team.fundamental" else "negative"
        return await _citing_reasoner(stance)(system, user, max_tokens, task)

    return reason


def test_slow_judge_yields_the_reports_without_verdict():
    experts = [e for e in _experts() if e.name in ("fundamental", "risk")]
    team = ExpertTeam(experts, TOOLS, _split_reasoner(5.0), judge_timeout_s=0.2)
    started = time.monotonic()
    result = asyncio.run(team.run(RunContext(tenant_id="a", ticker="X")))
    assert time.monotonic() - started < 2.0
    assert [r.status for r in result.reports] == ["ok", "ok"]
    assert [c["type"] for c in result.conflicts] == ["stance"]
    assert result.verdict == {"label": "neutral", "rationale": "", "source": "timeout"}


def test_fast_judge_still_decides():
    experts = [e for e in _experts() if e.name in ("fundamental", "risk")]
    team = ExpertTeam(experts, TOOLS, _split_reasoner(0.0), judge_timeout_s=0.5)
    result = asyncio.run(team.run(RunContext(tenant_id="a", ticker="X")))
    assert result.verdict == {"label": "negative", "rationale": "la deuda pesa más", "source": "judge"}


class _SlowJudge(_FakeProvider):
    """Fundamental a favor, el resto en contra; el juez tarda más que el chat."""

    async def complete(self, request):
        task = dict(request.metadata).get("expert_team_task", "")
        if "judge" in task:
            self.tasks.append("judge:slow")
            await asyncio.sleep(5)
        response = await super().complete(request)
        if "judge" in task:
            return response
        body = json.loads(response.message.content)
        body["stance"] = "positive" if "fundamental" in task else "negative"
        return LLMResponse(
            message=Message("assistant", json.dumps(body)), usage=Usage(), model="fake", provider="fake"
        )


def test_chat_slow_judge_keeps_the_team_answer(db, synthesis_calls, flag_on, monkeypatch):
    monkeypatch.setattr(team_chat, "CHAT_TEAM_TIMEOUT_S", 2.0)
    provider = _SlowJudge()
    response = _ask(db, QUESTION, provider)
    assert "judge:slow" in provider.tasks
    assert synthesis_calls == []
    assert response.model == "expert_team"
    assert "El juez no llegó a tiempo" in response.answer
    assert "Veredicto del juez" not in response.answer
    assert response.llm_trace["expert_team"]["judge"] == "timeout"


def test_judge_budget_fits_inside_the_chat_cap():
    for timeout in (45.0, 20.0, 4.0, 1.0):
        experts, judge = team_chat.team_budget_s(timeout), team_chat.judge_budget_s(timeout)
        assert judge > 0 and experts + judge < timeout
