"""Chat: «¿Compro más X? Dame tu opinión» no es una orden; y la lista de tesis no se ahoga en borradores.

Prueba real del chat (2026-11-03, cuenta de test): «¿Compro más MSFT? Dame tu
opinión sincera» contestaba «No ejecuto órdenes». Y «¿qué tesis tengo?»
volcaba cientos de borradores «vN, no activa» en orden alfabético.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, ThesisVersion
from app.services.chat_service import _ADVICE_QUESTION_RE, ChatService
from tests.test_expert_team_chat import (  # noqa: F401 — fixtures compartidas
    _ask,
    _clear_settings,
    _FakeProvider,
    db,
    synthesis_calls,
)


@pytest.mark.parametrize(
    "question",
    [
        "¿Compro más CHAT? Dame tu opinión sincera",
        "¿Vendo CHAT?",
        "Dame tu opinión sobre comprar CHAT",
        "¿Qué piensas de comprar más CHAT?",
        "What do you think, should I buy CHAT?",
    ],
)
def test_pedir_opinion_o_preguntar_con_signo_no_es_una_orden(db, question):
    assert _ADVICE_QUESTION_RE.search(question)
    response = _ask(db, question, _FakeProvider())
    assert (response.llm_trace or {}).get("path") != "order_verb"
    assert "No ejecuto órdenes" not in response.answer


@pytest.mark.parametrize("question", ["Compra 10 acciones de CHAT", "Vende mis acciones de CHAT"])
def test_las_ordenes_siguen_sin_ejecutarse(db, question):
    assert not _ADVICE_QUESTION_RE.search(question)
    response = _ask(db, question, _FakeProvider())
    assert (response.llm_trace or {}).get("path") == "order_verb"


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las tesis guardadas no deben pasar por el LLM")


def test_lista_de_tesis_limita_los_borradores():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    for index in range(12):
        company = Company(ticker=f"T{index:02d}", name=f"T{index} Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        session.add(company)
        session.flush()
        session.add(ThesisVersion(tenant_id=1, company_id=company.id, version=1, status="draft",
                                  thesis_markdown="# Tesis", executive_summary="Resumen"))
    session.commit()
    response = asyncio.run(ChatService(provider=_NoLLM()).answer(session, "¿Qué tesis tengo?", "global", None))
    assert response.llm_trace["path"] == "portfolio_theses"
    assert response.answer.count("no activa") == 5
    assert "y 7 empresas más" in response.answer
