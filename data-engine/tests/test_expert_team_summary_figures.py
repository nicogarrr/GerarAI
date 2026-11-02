"""El resumen de cada experto y la frase del juez tampoco pueden traer cifras inventadas.

El validador ya descartaba afirmaciones con números que no están en la
evidencia citada, pero el «summary» se pintaba tal cual (chat y tesis): un
modelo podía colar «ingresos de 999 millones» ahí. Ahora el resumen pasa el
mismo validador contra la evidencia de ESE experto; si trae una cifra sin
fuente, se queda vacío y siguen las afirmaciones validadas. Igual la frase
del juez: solo puede usar cifras de las afirmaciones validadas que vio. LLM FALSO.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services.expert_team.coordinator import ExpertTeam
from app.services.expert_team.experts import ExpertSpec
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec


def _team(summary: str) -> ExpertTeam:
    def facts(_ctx: RunContext) -> list[ToolOutput]:
        return [
            ToolOutput(
                source={"table": "financial_facts", "period": "FY2025"},
                data={"revenue": 130, "net_income": 20},
            )
        ]

    async def reasoner(_system: str, user: str, _max_tokens: int, _task: str) -> str:
        ids = [ev["id"] for ev in json.loads(user)["evidence"]]
        return json.dumps(
            {
                "summary": summary,
                "stance": "positive",
                "claims": [{"text": "Ingresos de 130", "numbers": [130], "citations": ids}],
            }
        )

    spec = ExpertSpec(name="fundamental", prompt_name="expert_fundamental", tools=("financial_facts",))
    return ExpertTeam([spec], {"financial_facts": ToolSpec("financial_facts", facts)}, reasoner)


def _run(summary: str):
    ctx = RunContext(tenant_id=1, ticker="ABC", mode="thesis")
    return asyncio.run(_team(summary).run(ctx)).reports[0]


@pytest.mark.parametrize(
    "summary", ["Ingresos de 999 millones y PER de 77", "Net income of 45 and margin 31.5%"]
)
def test_resumen_con_cifra_sin_fuente_se_quita(summary):
    report = _run(summary)
    assert report.status == "ok"
    assert report.summary == ""
    # Las afirmaciones validadas siguen ahí.
    assert [c.text for c in report.claims] == ["Ingresos de 130"]


@pytest.mark.parametrize(
    "summary",
    [
        "Crece con ingresos de 130 y beneficio de 20",
        "Negocio sólido y rentable",
        "Revenue of 130 and net income of 20, 2 segments",
    ],
)
def test_resumen_con_cifras_de_la_evidencia_se_mantiene(summary):
    assert _run(summary).summary == summary


def _judged(rationale: str) -> dict:
    def facts(_ctx: RunContext) -> list[ToolOutput]:
        return [
            ToolOutput(
                source={"table": "financial_facts", "period": "FY2025"},
                data={"revenue": 130, "net_income": 20},
            )
        ]

    async def reasoner(_system: str, user: str, _max_tokens: int, task: str) -> str:
        if task == "expert_team.judge":
            return f"VEREDICTO: bullish | {rationale}"
        ids = [ev["id"] for ev in json.loads(user)["evidence"]]
        stance = "positive" if task.endswith(".a") else "negative"
        return json.dumps(
            {
                "summary": "",
                "stance": stance,
                "claims": [
                    {"text": "Ingresos de 130 y beneficio de 20", "numbers": [130, 20], "citations": ids}
                ],
            }
        )

    specs = [
        ExpertSpec(name=name, prompt_name="expert_fundamental", tools=(f"facts_{name}",))
        for name in ("a", "b")
    ]
    tools = {f"facts_{name}": ToolSpec(f"facts_{name}", facts) for name in ("a", "b")}
    team = ExpertTeam(specs, tools, reasoner)
    verdict = asyncio.run(team.run(RunContext(tenant_id=1, ticker="ABC", mode="thesis"))).verdict
    assert verdict is not None
    return verdict


def test_frase_del_juez_con_cifra_inventada_no_se_ensena():
    verdict = _judged("los ingresos de 999 millones y un PER de 12,5 lo justifican")
    assert verdict["label"] == "positive"
    assert verdict["source"] == "judge"
    assert verdict["rationale"] == ""


def test_frase_del_juez_con_cifras_de_las_afirmaciones_se_mantiene():
    verdict = _judged("ingresos de 130 frente a un beneficio de 20; pesa más el crecimiento")
    assert verdict["rationale"] == "ingresos de 130 frente a un beneficio de 20; pesa más el crecimiento"
