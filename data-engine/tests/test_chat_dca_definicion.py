"""«¿Qué es el DCA?» se contesta con la definición (benchmark Cerebro, 2026-11-08).

Antes cualquier pregunta con «DCA» iba a tus niveles guardados: «¿Qué es el
DCA?» devolvía «Niveles DCA guardados: 4X DCA: ASTS, FRPH…» o «Sin nivel DCA».
Una pregunta de definición exacta va al glosario revisado; una pregunta por tus
niveles sigue yendo a tus niveles.
"""

import pytest

from app.llm.general_concepts import local_definition
from app.services import brain_context_tools as bct


@pytest.mark.parametrize(
    "question", ["¿Qué es el DCA?", "Explícame qué es el DCA", "que es dca", "¿Cómo funciona el DCA?"]
)
def test_dca_definition_question_gets_the_glossary(question):
    def _no_company():
        raise AssertionError("una definición no busca empresa")

    resp = bct.answer_context_question(None, question, 1, _no_company)  # type: ignore[arg-type]
    assert resp is not None
    assert resp.llm_trace["path"] == "local_educational"
    assert "1X a 4X" in resp.answer and "aportación base" in resp.answer
    assert "Niveles DCA guardados" not in resp.answer


@pytest.mark.parametrize("question", ["¿En qué nivel DCA está POOL?", "¿Qué señales DCA tengo activas?"])
def test_level_questions_still_read_your_levels(monkeypatch, question):
    seen = {}

    def _fake(db, tenant, company):
        seen["called"] = True
        return bct._response(["tus niveles"], [], "dca_level")

    monkeypatch.setattr(bct, "dca_answer", _fake)
    resp = bct.answer_context_question(None, question, 1, lambda: None)  # type: ignore[arg-type]
    assert seen.get("called") and resp is not None and resp.llm_trace["path"] == "dca_level"


def test_definition_is_exact_question_only():
    assert local_definition("¿Qué es el DCA de POOL este mes?") is None
