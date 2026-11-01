"""Resumen compacto por experto en la traza del chat (lo pinta el Cerebro).

Cuando contesta el equipo de expertos, ``llm_trace.expert_team.experts``
trae, por experto: su postura, cuántas afirmaciones quedaron con fuente y
cuántas se descartaron, y una confianza (alta/media/baja) que sale SOLO de
esas cuentas — no la inventa el modelo. Modelo falso, sin red.
"""

from __future__ import annotations

import pytest

from app.services.expert_team import chat as team_chat
from app.services.expert_team.models import Claim, ExpertReport, RunContext, TeamResult
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    flag_on,
    synthesis_calls,
)


@pytest.mark.parametrize(
    ("valid", "dropped", "level"),
    [
        (3, 0, "high"),
        (4, 1, "high"),
        (2, 0, "medium"),
        (3, 2, "medium"),
        (1, 1, "medium"),
        (1, 2, "low"),
        (0, 0, None),
        (0, 3, None),
    ],
)
def test_confidence_comes_from_the_counts(valid, dropped, level):
    assert team_chat.expert_confidence(valid, dropped) == level


def _claim(ok: bool) -> Claim:
    return Claim(text="x", citations=("ev-1",), reason="" if ok else "sin fuente")


def test_trace_has_a_compact_summary_per_expert():
    result = TeamResult(
        context=RunContext(tenant_id=1, ticker="X", mode="chat"),
        plan=["fundamental", "valuation", "risk"],
        reports=[
            ExpertReport(expert="fundamental", status="ok", stance="positive", claims=[_claim(True)] * 3),
            ExpertReport(
                expert="risk",
                status="ok",
                stance="negative",
                claims=[_claim(True)],
                dropped=[_claim(False), _claim(False)],
            ),
            ExpertReport(expert="valuation", status="timeout"),
        ],
        sources=[{"id": "ev-1", "tool": "financial_facts", "table": "financial_facts"}],
    )
    response = team_chat.render(result, "es")
    assert response is not None
    assert response.llm_trace["expert_team"]["experts"] == [
        {"expert": "fundamental", "status": "ok", "stance": "positive", "cited": 3, "dropped": 0, "confidence": "high"},
        {"expert": "risk", "status": "ok", "stance": "negative", "cited": 1, "dropped": 2, "confidence": "low"},
        {"expert": "valuation", "status": "timeout", "stance": "neutral", "cited": 0, "dropped": 0, "confidence": None},
    ]


def test_chat_answer_carries_the_summary(db, synthesis_calls, flag_on):
    response = _ask(db, "¿Merece la pena CHAT?", _FakeProvider())
    assert response.model == "expert_team"
    summary = response.llm_trace["expert_team"]["experts"]
    assert [row["expert"] for row in summary] == response.llm_trace["expert_team"]["plan"]
    answered = [row for row in summary if row["cited"]]
    assert answered and all(row["confidence"] in {"high", "medium", "low"} for row in answered)
