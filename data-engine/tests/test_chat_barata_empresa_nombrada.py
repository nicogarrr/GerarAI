"""Chat: «¿Uber está barata?» habla de Uber, como «¿Uber está cara?».

Prueba real 2026-11-03 (cerebro-real-2, OpenCode Go): «¿Uber está cara?» iba a
la empresa (precio, cifras, tesis y, con el equipo encendido, el experto de
valoración), pero «¿Uber tiene mucha deuda y está barata?» o «Is Uber
cheap?» caían en el resumen personal de «¿qué compro hoy?» («Lecturas
guardadas, no cotizaciones en directo…») y no hablaban de Uber. Una pregunta
de compra sin empresa («¿qué debo comprar hoy?», «¿qué está barato de mi
watchlist?») sigue en el resumen personal.
"""

import asyncio

import pytest

from app.core.i18n import reset_language_scope, set_language_scope
from app.services.chat_service import ChatService
from tests.cerebro_seed import seeded_session


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _ask(question, *, lang="es", scope="portfolio", ticker=None):
    token = set_language_scope(lang)
    try:
        db = seeded_session()
        db.info["language"] = lang
        return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, scope, ticker))
    finally:
        reset_language_scope(token)


@pytest.mark.parametrize(
    ("question", "lang"),
    [
        ("¿Uber está barata?", "es"),
        ("¿Uber tiene mucha deuda y está barata?", "es"),
        ("¿Está infravalorada Uber?", "es"),
        ("Is Uber cheap?", "en"),
        ("Is UBER undervalued right now?", "en"),
    ],
)
def test_named_company_cheap_question_is_about_the_company(question, lang):
    response = _ask(question, lang=lang)
    assert (response.llm_trace or {}).get("path") != "personal_context"
    assert "UBER" in response.answer


def test_cheap_question_on_company_page_is_about_that_company():
    response = _ask("¿Está barata?", scope="company", ticker="UBER")
    assert (response.llm_trace or {}).get("path") != "personal_context"
    assert "UBER" in response.answer


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué debo comprar hoy?",
        "¿Qué está barato de mi watchlist?",
        "¿Qué debo comprar hoy de UBER con mi aportación?",
        "¿Uber es lo más barato de mi watchlist?",
    ],
)
def test_purchase_questions_keep_the_personal_snapshot(question):
    response = _ask(question)
    assert (response.llm_trace or {}).get("path") == "personal_context"
