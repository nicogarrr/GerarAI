"""Chat: el experto de noticias entra cuando la pregunta lo pide, no solo con «noticia».

Antes solo se activaba si la pregunta decía «noticia», «prensa», «titular»…
«¿Por qué ha caído CHAT? ¿Está cara?» o «¿Merece la pena CHAT?» no le
preguntaban, aunque lo reciente es justo lo que explica la caída. Sigue sin
entrar en preguntas sin nada reciente («¿qué valoración tiene CHAT?»).
Detrás de EXPERT_TEAM_ENABLED; sin LLM ni red (plan determinista).
"""

from __future__ import annotations

import pytest

from app.services.expert_team import chat as team_chat


@pytest.mark.parametrize(
    "question",
    [
        "¿Merece la pena CHAT?",
        "¿Por qué ha caído CHAT? ¿Está cara?",
        "¿Qué ha pasado con CHAT últimamente y qué riesgo tiene?",
        "CHAT se desploma hoy, ¿es buena compra?",
        "¿Qué ha anunciado CHAT esta semana y cómo afecta a su valoración?",
        "Why is CHAT dropping? Is it expensive?",
        "What happened to CHAT recently and what are the risks?",
        "Is CHAT worth buying?",
    ],
)
def test_news_joins_when_relevant(question):
    assert "news" in team_chat.plan_for(question, "CHAT")


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué valoración tiene CHAT y qué riesgo?",
        "¿Cómo van los ingresos y el margen de CHAT?",
        "What is CHAT's fair value and its risk?",
    ],
)
def test_news_stays_out_without_anything_recent(question):
    assert "news" not in team_chat.plan_for(question, "CHAT")


def test_why_did_it_fall_alone_is_still_one_expert():
    # Una sola pregunta de noticias sigue por la síntesis de siempre (MIN_EXPERTS).
    assert team_chat.plan_for("¿Qué ha pasado con CHAT?", "CHAT") == ["news"]
