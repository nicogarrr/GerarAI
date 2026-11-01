"""Núcleo del equipo de expertos: plan, paralelo acotado, timeout, citas, aislamiento.

Todo con LLM FALSO y herramientas falsas: sin red, sin BD.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from app.services.expert_team import (
    ExpertSpec,
    ExpertTeam,
    RunContext,
    ToolOutput,
    ToolSpec,
    expert_team_enabled,
)


def _tool(name: str, data_by_tenant: dict[str, dict] | None = None, *, table: str = "t"):
    def fn(ctx: RunContext) -> ToolOutput | None:
        data = (data_by_tenant or {}).get(ctx.tenant_id, {"ticker": ctx.ticker, "value": 10.0})
        return ToolOutput(source={"table": table, "date": "2026-10-31"}, data=data)

    return ToolSpec(name=name, fn=fn)


def _citing_reasoner(stance: str = "neutral", *, delay: float = 0.0, calls: list | None = None):
    """Cita todo lo que ve y repite el primer número de cada evidencia."""

    async def reason(system: str, user: str, max_tokens: int, task: str) -> str:
        if calls is not None:
            calls.append((task, user))
        if delay:
            await asyncio.sleep(delay)
        payload = json.loads(user)
        claims = []
        for ev in payload["evidence"]:
            numbers = [v for v in ev["data"].values() if isinstance(v, int | float)]
            claims.append({"text": f"dato {ev['id']} {ev['data'].get('secret', '')}".strip(), "numbers": numbers[:1], "citations": [ev["id"]]})
        return json.dumps({"summary": "ok", "stance": stance, "claims": claims})

    return reason


TOOLS = {n: _tool(n) for n in ("facts", "valuation", "risk", "news", "tax")}


def _experts(**timeouts: float) -> list[ExpertSpec]:
    return [
        ExpertSpec(name="fundamental", prompt_name="thesis_debate_bull", tools=("facts",), keywords=("ingresos",)),
        ExpertSpec(name="valuation", prompt_name="thesis_debate_bull", tools=("valuation",), keywords=("valoracion", "dcf")),
        ExpertSpec(name="risk", prompt_name="thesis_debate_bear", tools=("risk",), keywords=("riesgo",)),
        ExpertSpec(
            name="news",
            prompt_name="thesis_debate_bull",
            tools=("news",),
            keywords=("noticia",),
            timeout_s=timeouts.get("news", 5.0),
        ),
        ExpertSpec(
            name="tax",
            prompt_name="thesis_debate_bull",
            tools=("tax",),
            keywords=("irpf", "impuesto"),
            applies=lambda ctx: ctx.holds_position,
        ),
    ]


def test_flag_default_off():
    assert expert_team_enabled() is False


def test_whitelist_rejects_unknown_tool():
    with pytest.raises(ValueError, match="unknown tool"):
        ExpertTeam([ExpertSpec(name="x", prompt_name="p", tools=("nope",))], TOOLS, _citing_reasoner())


def test_plan_thesis_all_experts_tax_only_with_position():
    team = ExpertTeam(_experts(), TOOLS, _citing_reasoner())
    assert team.plan(RunContext(tenant_id="a", ticker="MSFT")) == ["fundamental", "valuation", "risk", "news"]
    assert "tax" in team.plan(RunContext(tenant_id="a", ticker="MSFT", holds_position=True))


def test_plan_chat_by_keywords_accent_insensitive():
    team = ExpertTeam(_experts(), TOOLS, _citing_reasoner())
    ctx = RunContext(tenant_id="a", ticker="MSFT", mode="chat", question="¿Qué RIESGO y qué valoración tiene?")
    assert team.plan(ctx) == ["valuation", "risk"]
    assert team.plan(RunContext(tenant_id="a", mode="chat", question="hola")) == []


def test_run_merges_cited_claims_and_sources():
    team = ExpertTeam(_experts(), TOOLS, _citing_reasoner())
    result = asyncio.run(team.run(RunContext(tenant_id="a", ticker="MSFT")))
    assert [r.expert for r in result.reports] == ["fundamental", "valuation", "risk", "news"]
    assert all(r.status == "ok" and r.claims for r in result.reports)
    cited = {c for r in result.reports for claim in r.claims for c in claim.citations}
    assert cited == {s["id"] for s in result.sources}
    assert all(s["table"] == "t" and s["date"] == "2026-10-31" for s in result.sources)
    json.dumps(result.to_dict())


def test_parallelism_is_bounded():
    live = {"now": 0, "max": 0}

    async def reason(system, user, max_tokens, task):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await asyncio.sleep(0.05)
        live["now"] -= 1
        return json.dumps({"summary": "", "stance": "neutral", "claims": []})

    team = ExpertTeam(_experts(), TOOLS, reason, max_parallel=2)
    asyncio.run(team.run(RunContext(tenant_id="a", ticker="X", holds_position=True)))
    assert live["max"] == 2


def test_one_expert_timeout_degrades_gracefully():
    slow = _citing_reasoner()

    async def reason(system, user, max_tokens, task):
        if task == "expert_team.news":
            await asyncio.sleep(5)
        return await slow(system, user, max_tokens, task)

    team = ExpertTeam(_experts(news=0.05), TOOLS, reason)
    result = asyncio.run(team.run(RunContext(tenant_id="a", ticker="X")))
    by = {r.expert: r for r in result.reports}
    assert by["news"].status == "timeout" and by["news"].claims == []
    assert all(by[n].status == "ok" for n in ("fundamental", "valuation", "risk"))


def test_expert_error_and_bad_json_do_not_break_run():
    async def reason(system, user, max_tokens, task):
        if task == "expert_team.risk":
            raise RuntimeError("boom")
        if task == "expert_team.news":
            return "no es json"
        return json.dumps({"summary": "", "stance": "neutral", "claims": []})

    result = asyncio.run(ExpertTeam(_experts(), TOOLS, reason).run(RunContext(tenant_id="a", ticker="X")))
    by = {r.expert: r for r in result.reports}
    assert by["risk"].status == "error" and by["risk"].error == "RuntimeError"
    assert by["news"].status == "error" and by["news"].llm_calls == 2  # un reintento de formato
    assert by["fundamental"].status == "ok"


def test_claims_with_foreign_or_invented_citations_are_dropped():
    async def reason(system, user, max_tokens, task):
        own = json.loads(user)["evidence"][0]["id"]
        return json.dumps(
            {
                "summary": "",
                "stance": "neutral",
                "claims": [
                    {"text": "bien", "numbers": [10.0], "citations": [own]},
                    {"text": "inventada", "numbers": [99], "citations": ["ev-999"]},
                    {"text": "sin cita", "numbers": [], "citations": []},
                ],
            }
        )

    team = ExpertTeam(_experts(), TOOLS, reason)
    result = asyncio.run(team.run(RunContext(tenant_id="a", ticker="X")))
    for report in result.reports:
        assert [c.text for c in report.claims] == ["bien"]
        assert sorted(c.text for c in report.dropped) == ["inventada", "sin cita"]


def test_no_evidence_means_no_llm_call():
    empty = ToolSpec(name="facts", fn=lambda ctx: None)
    calls: list = []
    team = ExpertTeam(
        [ExpertSpec(name="fundamental", prompt_name="thesis_debate_bull", tools=("facts",))],
        {"facts": empty},
        _citing_reasoner(calls=calls),
    )
    result = asyncio.run(team.run(RunContext(tenant_id="a", ticker="X")))
    assert result.reports[0].status == "no_data" and calls == []


def test_per_user_isolation_in_concurrent_runs():
    data = {"tenant-a": {"secret": "A-ONLY", "value": 1.0}, "tenant-b": {"secret": "B-ONLY", "value": 2.0}}
    tools = {n: _tool(n, data) for n in TOOLS}
    calls: list = []
    team = ExpertTeam(_experts(), tools, _citing_reasoner(delay=0.01, calls=calls))

    async def both():
        return await asyncio.gather(
            team.run(RunContext(tenant_id="tenant-a", ticker="X")),
            team.run(RunContext(tenant_id="tenant-b", ticker="X")),
        )

    res_a, res_b = asyncio.run(both())
    blob_a, blob_b = json.dumps(res_a.to_dict()), json.dumps(res_b.to_dict())
    assert "A-ONLY" in blob_a and "B-ONLY" not in blob_a
    assert "B-ONLY" in blob_b and "A-ONLY" not in blob_b
    prompts_with_a = [u for _, u in calls if "A-ONLY" in u]
    assert prompts_with_a and all("B-ONLY" not in u for u in prompts_with_a)


def test_tool_gets_only_server_context():
    seen = []

    def fn(ctx):
        seen.append(ctx)
        return ToolOutput(source={"table": "t"}, data={"v": 1})

    team = ExpertTeam(
        [ExpertSpec(name="fundamental", prompt_name="thesis_debate_bull", tools=("facts",))],
        {"facts": ToolSpec(name="facts", fn=fn)},
        _citing_reasoner(),
    )
    ctx = RunContext(tenant_id="a", user_id="u1", ticker="X")
    asyncio.run(team.run(ctx))
    assert seen == [ctx]


def test_metric_conflict_reported_with_both_sources():
    async def reason(system, user, max_tokens, task):
        ev = json.loads(user)["evidence"][0]
        value = 10.0 if task == "expert_team.fundamental" else 20.0
        return json.dumps(
            {"summary": "", "stance": "neutral", "claims": [
                {"text": "margen", "numbers": [value], "metric": "operating_margin", "citations": [ev["id"]]}
            ]}
        )

    experts = _experts()[:2]
    result = asyncio.run(ExpertTeam(experts, TOOLS, reason).run(RunContext(tenant_id="a", ticker="X")))
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict["type"] == "metric" and conflict["metric"] == "operating_margin"
    assert sorted(v["value"] for v in conflict["values"]) == [10.0, 20.0]


def test_stance_conflict_goes_to_judge_and_failure_is_unresolved():
    async def reason(system, user, max_tokens, task):
        if task == "expert_team.judge":
            assert "dato" in user
            return "VEREDICTO: bearish | la deuda pesa más"
        stance = "positive" if task == "expert_team.fundamental" else "negative"
        return await _citing_reasoner(stance)(system, user, max_tokens, task)

    experts = [e for e in _experts() if e.name in ("fundamental", "risk")]
    result = asyncio.run(ExpertTeam(experts, TOOLS, reason).run(RunContext(tenant_id="a", ticker="X")))
    assert [c["type"] for c in result.conflicts] == ["stance"]
    assert result.verdict == {"label": "negative", "rationale": "la deuda pesa más", "source": "judge"}

    async def broken(system, user, max_tokens, task):
        if task == "expert_team.judge":
            raise RuntimeError("down")
        return await reason(system, user, max_tokens, task)

    result = asyncio.run(ExpertTeam(experts, TOOLS, broken).run(RunContext(tenant_id="a", ticker="X")))
    assert result.verdict is not None and result.verdict["source"] == "unresolved"


def test_run_guard_is_active_inside_experts():
    from app.llm import run_guard

    seen = []

    async def reason(system, user, max_tokens, task):
        seen.append(run_guard.current_guard())
        return json.dumps({"summary": "", "stance": "neutral", "claims": []})

    guard = run_guard.LLMRunGuard(
        run_id="r1",
        allowed_hosts=frozenset({"x"}),
        allowed_models=frozenset({"m"}),
        max_posts=5,
        max_tokens_per_request=100,
        max_total_output_tokens=500,
        store=run_guard.InMemoryCounterStore(),
    )
    asyncio.run(ExpertTeam(_experts(), TOOLS, reason, guard=guard).run(RunContext(tenant_id="a", ticker="X")))
    assert seen and all(g is guard for g in seen)
    assert run_guard.current_guard() is None


def test_guard_abort_marks_expert_error():
    from app.llm.run_guard import LLMGuardAbort

    async def reason(system, user, max_tokens, task):
        raise LLMGuardAbort("run_budget_exhausted")

    result = asyncio.run(ExpertTeam(_experts()[:1], TOOLS, reason).run(RunContext(tenant_id="a", ticker="X")))
    assert result.reports[0].status == "error"
    assert re.search("run_budget_exhausted", result.reports[0].error or "")
