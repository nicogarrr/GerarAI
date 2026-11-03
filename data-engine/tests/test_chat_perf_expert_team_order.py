"""Rendimiento del equipo de expertos: con más expertos que huecos, los lentos empiezan primero.

LLM FALSO con latencia fija por experto (proporcional a la mediana real medida con
OpenCode Go el 3 nov 2026: fundamental 14 s, fiscal 12 s, riesgo 11 s, noticias 6 s,
valoración 5 s). Sin red, sin BD. La respuesta final no cambia: misma salida que sin
tope de paralelo y mismos ids de evidencia (en el orden del plantel).
"""

from __future__ import annotations

import asyncio
import json
import time

from app.services.expert_team import ExpertTeam, RunContext, ToolOutput, ToolSpec
from app.services.expert_team.roster import default_experts

SCALE = 0.02  # 14 s reales -> 0,28 s de prueba
TOOL_NAMES = (
    "financial_facts",
    "valuation_engine",
    "risk_events",
    "portfolio_concentration",
    "news_events",
    "user_position",
    "irpf_savings_bands",
    "sale_tax_estimate",
)


def _tools() -> dict[str, ToolSpec]:
    def make(name: str):
        def fn(ctx: RunContext) -> ToolOutput:
            return ToolOutput(source={"table": name, "date": "2026-10-31"}, data={"tool": name, "value": 10.0})

        return ToolSpec(name=name, fn=fn)

    return {n: make(n) for n in TOOL_NAMES}


def _experts():
    # El fiscal solo entra con posición y palabra fiscal: aquí siempre, para tener 5 expertos.
    experts = default_experts()
    for spec in experts:
        object.__setattr__(spec, "applies", None)
    return experts


def _reasoner(starts: list[str]):
    typical = {s.name: s.typical_s for s in default_experts()}

    async def reason(system: str, user: str, max_tokens: int, task: str) -> str:
        name = task.removeprefix("expert_team.")
        starts.append(name)
        await asyncio.sleep(typical.get(name, 1.0) * SCALE)
        payload = json.loads(user)
        claims = [
            {"text": f"{name} dato {ev['id']} vale 10", "numbers": [10.0], "citations": [ev["id"]]}
            for ev in payload["evidence"]
        ]
        return json.dumps({"summary": "", "stance": "neutral", "claims": claims})

    return reason


def _ctx() -> RunContext:
    return RunContext(
        tenant_id=1,
        ticker="UBER",
        question="¿merece la pena Uber? riesgo, valoración, noticias, ingresos e impuestos",
        mode="chat",
        holds_position=True,
    )


def _run(max_parallel: int):
    starts: list[str] = []
    team = ExpertTeam(_experts(), _tools(), _reasoner(starts), max_parallel=max_parallel)
    t0 = time.perf_counter()
    result = asyncio.run(team.run(_ctx()))
    return result, starts, time.perf_counter() - t0


def test_plan_has_five_experts_for_three_slots():
    result, _, _ = _run(3)
    assert result.plan == ["fundamental", "valuation", "risk", "news", "tax"]


def test_slowest_experts_take_the_slots_first():
    _, starts, elapsed = _run(3)
    assert set(starts[:3]) == {"fundamental", "tax", "risk"}
    assert starts[3:] == ["news", "valuation"]
    # Antes (orden del plantel): el fiscal esperaba a valoración -> 0,05·SCALE... ≈ 0,46 s;
    # ahora ≈ 0,36 s (el más lento manda). Margen amplio para no fallar con carga.
    assert elapsed < 0.44


def test_same_output_as_without_parallel_cap():
    capped, _, _ = _run(3)
    free, _, _ = _run(5)
    assert json.dumps(capped.to_dict(), sort_keys=True, default=str) == json.dumps(
        free.to_dict(), sort_keys=True, default=str
    )


def test_evidence_ids_follow_roster_order():
    result, _, _ = _run(3)
    ids = {s["tool"]: s["id"] for s in result.sources}
    assert ids["financial_facts"] == "ev-1"
    assert ids["valuation_engine"] == "ev-2"
    assert ids["risk_events"] == "ev-3"
    assert ids["portfolio_concentration"] == "ev-4"
    assert ids["news_events"] == "ev-5"
    assert ids["user_position"] == "ev-6"


def test_expert_timeout_still_counts_evidence_time():
    slow_tool_s = 0.2

    async def slow(ctx: RunContext) -> ToolOutput:
        await asyncio.sleep(slow_tool_s)
        return ToolOutput(source={"table": "news_events"}, data={"value": 1.0})

    tools = _tools()
    tools["news_events"] = ToolSpec(name="news_events", fn=slow)
    experts = _experts()
    for spec in experts:
        if spec.name == "news":
            object.__setattr__(spec, "timeout_s", slow_tool_s + 0.5 * spec.typical_s * SCALE)
    team = ExpertTeam(experts, tools, _reasoner([]), max_parallel=3)
    result = asyncio.run(team.run(_ctx()))
    by = {r.expert: r.status for r in result.reports}
    assert by["news"] == "timeout"
    assert by["fundamental"] == "ok" and by["tax"] == "ok"
