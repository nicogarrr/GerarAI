"""Chat en inglés: respuesta general sin ticker (texto y panel plegado).

Con el inglés elegido, una pregunta sin ticker («What should I watch this week?»)
seguía respondiendo «CONTEXTO / SIN CALCULOS / MEMORIAS…», el panel «Ver detalle»
y las acciones propuestas en castellano. En español nada cambia.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import _request_language, set_language_scope
from app.models.entities import Base
from app.services.chat_service import ChatService


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _general(language: str):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.info["language"] = language
    token = set_language_scope(language)
    try:
        return ChatService()._deterministic_answer(db, "general question", "portfolio", None)
    finally:
        _request_language.reset(token)
        db.close()


_SPANISH = (
    "CONTEXTO", "Pregunta general sin ticker", "SIN CALCULOS", "MEMORIAS", "No se recuperó memoria",
    "SIN AFIRMACIONES", "Pregunta por un ticker", "Solo contexto de memorias", "No se hizo ningún cálculo",
    "Memorias de cartera recuperadas", "Hace falta un ticker", "No se seleccionaron", "Indica un ticker",
    "No hay conclusión", "Ingiere documentos",
)


def test_general_answer_in_english():
    response = _general("en")
    assert response.answer.startswith("CONTEXT\n- General question with no ticker")
    assert "- No relevant portfolio memory was retrieved." in response.answer
    assert "NO COMPANY CLAIMS" in response.answer
    bodies = {section.key: section.body for section in response.sections}
    assert bodies["calculations"] == "No portfolio calculation was made."
    assert bodies["conclusion"] == "No company conclusion available."
    assert response.proposed_actions == ["Ask about a ticker", "Ingest portfolio documents"]
    visible = response.answer + "\n".join(bodies.values()) + "\n".join(response.proposed_actions)
    for spanish in _SPANISH:
        assert spanish not in visible


def test_general_answer_unchanged_in_spanish():
    response = _general("es")
    assert response.answer.startswith("CONTEXTO\n- Pregunta general sin ticker")
    assert "- No se recuperó memoria de cartera relevante." in response.answer
    bodies = {section.key: section.body for section in response.sections}
    assert bodies["calculations"] == "No se hizo ningún cálculo de cartera."
    assert response.proposed_actions == ["Pregunta por un ticker", "Ingiere documentos de cartera"]

