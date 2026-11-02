"""El veredicto del juez sale traducido (no «positive» en mitad del castellano).

El juez guarda su etiqueta como «positive»/«negative»/«neutral» (las mismas
palabras que la postura de cada experto), pero el chat y la tesis guardada
solo traducían «bullish»/«bearish»: en castellano salía «Veredicto del juez:
positive». Ahora las dos formas se traducen (solo al mostrar: las corridas
guardadas no se tocan). Modelo falso, sin red.
"""

from __future__ import annotations

import json

import pytest

from app.llm import LLMResponse, Message, Usage
from app.models.entities import WorkflowRun
from app.services.expert_team import view as expert_view
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    flag_on,
    synthesis_calls,
)

QUESTION = "¿Merece la pena CHAT?"


class _SplitWithJudge(_FakeProvider):
    """Fundamental a favor, el resto en contra; el juez decide «bullish»."""

    async def complete(self, request):
        task = dict(request.metadata).get("expert_team_task", "")
        if "judge" in task:
            return LLMResponse(
                message=Message("assistant", "VEREDICTO: bullish | el crecimiento pesa más"),
                usage=Usage(), model="fake", provider="fake",
            )
        response = await super().complete(request)
        body = json.loads(response.message.content)
        body["stance"] = "positive" if "fundamental" in task else "negative"
        return LLMResponse(message=Message("assistant", json.dumps(body)), usage=Usage(), model="fake", provider="fake")


def test_chat_verdict_is_in_spanish(db, synthesis_calls, flag_on):
    response = _ask(db, QUESTION, _SplitWithJudge())
    assert response.model == "expert_team"
    assert "Veredicto del juez: a favor. el crecimiento pesa más" in response.answer
    assert "positive" not in response.answer


def _run() -> WorkflowRun:
    return WorkflowRun(
        id=9, tenant_id=1, workflow_name="ExpertTeamThesisWorkflow", status="completed",
        input_payload={"ticker": "MSFT"}, result_payload={},
    )


def _result(label: str) -> dict:
    return {
        "context": {"tenant_id": 1, "ticker": "MSFT"},
        "reports": [{"expert": "fundamental", "status": "ok", "claims": [{"text": "x", "citations": [], "reason": ""}]}],
        "sources": [],
        "verdict": {"source": "judge", "label": label, "rationale": "r"},
    }


@pytest.mark.parametrize(
    ("label", "es", "en"),
    [("positive", "a favor", "positive"), ("negative", "en contra", "negative"), ("neutral", "neutral", "neutral"),
     ("bullish", "a favor", "positive"), ("bearish", "en contra", "negative")],
)
def test_saved_thesis_and_history_translate_the_judge_label(label, es, en):
    result = _result(label)
    view_es = expert_view.thesis_view(_run(), result, "es", [(_run(), result)])
    assert view_es.verdict is not None and view_es.verdict.label == es
    assert view_es.history[0].verdict == es
    view_en = expert_view.thesis_view(_run(), result, "en", [(_run(), result)])
    assert view_en.verdict is not None and view_en.verdict.label == en
    assert result["verdict"]["label"] == label  # no se reescribe lo guardado
