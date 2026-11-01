"""Revisión del equipo de expertos: fuentes con «id» propio y choques solo con afirmaciones con fuente.

1) Las herramientas de riesgo y de tesis guardada ponen en su fuente el «id»
   de la fila (``{"table": "risk_events", "id": "42"}``). Al juntar las fuentes,
   ese «id» pisaba el id de la evidencia («ev-3»): la afirmación de Riesgo se
   quedaba sin su [n] y dos filas con el mismo id (aviso 5 y tesis 5) se
   fundían en una sola fuente.
2) Los choques (postura y cifras) y el juez usaban también afirmaciones
   marcadas «sin fuente»; ahora solo las que tienen fuente.
Modelo y herramientas falsos, sin red ni BD.
"""

from __future__ import annotations

import asyncio
import json

from app.services.expert_team import ExpertTeam, RunContext, ToolOutput, ToolSpec
from app.services.expert_team import chat as team_chat
from app.services.expert_team.citations import citation_validator
from tests.test_expert_team_core import _citing_reasoner, _experts


def _row_tool(table: str, row_id: str, value: float) -> ToolSpec:
    def fn(ctx: RunContext) -> ToolOutput:
        return ToolOutput(source={"table": table, "id": row_id, "date": "2026-10-31"}, data={"value": value})

    return ToolSpec(name=table, fn=fn)


TOOLS = {
    "facts": _row_tool("financial_facts", "5", 10.0),
    "valuation": _row_tool("thesis_versions", "5", 20.0),
    "risk": _row_tool("risk_events", "5", 30.0),
    "news": _row_tool("news_events", "7", 1.0),
    "tax": _row_tool("tax", "8", 1.0),
}


def _team(reasoner, **kwargs) -> ExpertTeam:
    experts = [e for e in _experts() if e.name in ("fundamental", "valuation", "risk")]
    return ExpertTeam(experts, TOOLS, reasoner, **kwargs)


def test_row_id_in_the_source_does_not_replace_the_evidence_id():
    result = asyncio.run(_team(_citing_reasoner()).run(RunContext(tenant_id="a", ticker="X")))
    cited = {c for r in result.reports for claim in r.claims for c in claim.citations}
    assert len(cited) == 3
    assert {s["id"] for s in result.sources} == cited  # una fuente por evidencia, con su id
    assert sorted(s["row_id"] for s in result.sources) == ["5", "5", "5"]
    response = team_chat.render(result, "es")
    assert response is not None
    assert "**Riesgo**" in response.answer
    risk = next(s for s in response.sections if s.body.startswith("Riesgo"))
    assert risk.citations and "[3]" in risk.body


def test_conflicts_and_judge_ignore_unsourced_claims():
    seen: list[str] = []

    async def reason(system, user, max_tokens, task):
        if task == "expert_team.judge":
            seen.append(user)
            return "VEREDICTO: neutral | -"
        payload = json.loads(user)
        if task == "expert_team.risk":
            # cifra inventada: queda marcada «sin fuente» (modo mark)
            claims = [
                {
                    "text": "deuda de 999",
                    "numbers": [999.0],
                    "citations": [payload["evidence"][0]["id"]],
                    "metric": "operating_margin",
                }
            ]
            return json.dumps({"summary": "", "stance": "negative", "claims": claims})
        ev = payload["evidence"][0]
        claims = [
            {
                "text": "dato",
                "numbers": [ev["data"]["value"]],
                "citations": [ev["id"]],
                "metric": "operating_margin",
            }
        ]
        return json.dumps({"summary": "", "stance": "positive", "claims": claims})

    team = _team(reason, validator=citation_validator(mode="mark"))
    result = asyncio.run(team.run(RunContext(tenant_id="a", ticker="X")))
    risk = next(r for r in result.reports if r.expert == "risk")
    assert risk.claims and all(c.reason.startswith("mark:") for c in risk.claims)
    # Riesgo «en contra» sin ninguna afirmación con fuente: no hay choque de postura ni juez
    assert not any(c["type"] == "stance" for c in result.conflicts)
    assert result.verdict is None and seen == []
    # el choque de cifras solo compara las que tienen fuente (10 y 20), no el 999 inventado
    metric = next(c for c in result.conflicts if c["type"] == "metric")
    assert sorted(v["value"] for v in metric["values"]) == [10.0, 20.0]
