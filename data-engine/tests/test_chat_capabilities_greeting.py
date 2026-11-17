"""«Hola, ¿qué tal? ¿En qué me puedes ayudar hoy?» es la pregunta de capacidades.

Medido en prod 2026-11-17 (c31b, Audit): con la coletilla «hoy» no casaba con
_CAPABILITIES_RE, llegaba al generador libre y el guard de cartera lo rechazaba
(«falta tus posiciones»). Regresion: coletillas de tiempo/lugar y «ayudarme».
"""

import pytest

from app.services.brain_service import LEADING_GREETING_RE
from app.services.chat_service import _CAPABILITIES_RE


def _is_capabilities(question: str) -> bool:
    without_greeting = LEADING_GREETING_RE.sub("", question).strip()
    return bool(
        _CAPABILITIES_RE.match(question)
        or (without_greeting and _CAPABILITIES_RE.match(without_greeting))
    )


@pytest.mark.parametrize(
    "question",
    [
        "Hola, ¿qué tal? ¿En qué me puedes ayudar hoy?",
        "¿En qué me puedes ayudar hoy?",
        "hola, quien eres?",
        "¿Qué puedes hacer?",
        "¿Cómo puedes ayudarme?",
        "qué puedes hacer ahora mismo",
        "¿Qué puedes hacer en esta app?",
        "¿qué tal? ¿qué eres?",
    ],
)
def test_preguntas_de_capacidades_con_coletilla(question):
    assert _is_capabilities(question)


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué puedes hacer por Amazon?",
        "¿En qué me puedes ayudar con mi cartera?",
        "¿Qué puedes hacer con mis posiciones hoy?",
    ],
)
def test_preguntas_concretas_no_son_capacidades(question):
    assert not _is_capabilities(question)
