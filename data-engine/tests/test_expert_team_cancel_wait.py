"""Al vencer el tope total del equipo, esperar (con tope corto) a los expertos cancelados.

Antes, las tareas pendientes se cancelaban con ``task.cancel()`` y ``run()``
seguía sin esperarlas: el equipo devolvía su resultado (y llamaba al juez)
con expertos todavía vivos que solo terminaban de cancelarse más tarde, fuera
del control de la corrida. Ahora se espera a que acaben de cancelarse, como
mucho ``cancel_grace_s`` (corto, para no comerse el margen del chat), y un
experto que no se deja cancelar no bloquea la respuesta. LLM falso, sin red.
"""

from __future__ import annotations

import asyncio
import json
import time

from app.services.expert_team import ExpertSpec, ExpertTeam, RunContext, ToolOutput, ToolSpec

TOOLS = {"facts": ToolSpec(name="facts", fn=lambda ctx: ToolOutput(source={"table": "t"}, data={"v": 1.0}))}


def _spec(name: str) -> ExpertSpec:
    return ExpertSpec(name=name, prompt_name="thesis_debate_bull", tools=("facts",), timeout_s=30.0)


def _reasoner(events: list[str], *, stubborn: bool = False):
    async def reason(system: str, user: str, max_tokens: int, task: str) -> str:
        if task == "expert_team.fast":
            ev = json.loads(user)["evidence"][0]
            return json.dumps({"summary": "ok", "stance": "neutral", "claims": [{"text": "v", "citations": [ev["id"]]}]})
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            if stubborn:
                events.append("ignored")
                await asyncio.sleep(1.0)  # no se deja cancelar a la primera
                events.append("late")
                return json.dumps({"summary": "", "stance": "neutral", "claims": []})
            await asyncio.sleep(0.05)  # limpieza tras la cancelación
            events.append("cleaned")
            raise
        return "{}"

    return reason


def test_run_waits_for_cancelled_experts_to_finish():
    events: list[str] = []

    async def main():
        team = ExpertTeam([_spec("fast"), _spec("slow")], TOOLS, _reasoner(events), total_timeout_s=0.2)
        result = await team.run(RunContext(tenant_id="a", ticker="X"))
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        return result, others

    result, others = asyncio.run(main())
    assert events == ["cleaned"]  # la limpieza ya pasó cuando run() devuelve
    assert others == []  # no queda ningún experto vivo
    assert {r.expert: r.status for r in result.reports} == {"fast": "ok", "slow": "timeout"}


def test_stubborn_expert_does_not_block_the_answer():
    events: list[str] = []

    async def main():
        team = ExpertTeam(
            [_spec("fast"), _spec("slow")], TOOLS, _reasoner(events, stubborn=True), total_timeout_s=0.2, cancel_grace_s=0.1
        )
        started = time.monotonic()
        result = await team.run(RunContext(tenant_id="a", ticker="X"))
        elapsed = time.monotonic() - started
        return result, elapsed

    result, elapsed = asyncio.run(main())
    assert elapsed < 0.9  # tope 0,2 s + gracia 0,1 s, no el segundo del experto terco
    assert {r.expert: r.status for r in result.reports} == {"fast": "ok", "slow": "timeout"}
    assert "ignored" in events


def test_grace_is_short_by_default():
    team = ExpertTeam([_spec("fast")], TOOLS, _reasoner([]))
    assert 0 < team.cancel_grace_s <= 1.0
