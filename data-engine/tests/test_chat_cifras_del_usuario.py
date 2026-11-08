"""Las cifras que da el propio usuario no son cifras inventadas (benchmark Cerebro, 2026-11-08).

«¿Y si este mes aporto los 600 € del plan, cuánto tendría?» devolvía «No puedo
responderte con fuentes ahora mismo»: la respuesta repetía «600 €» sin
«unos/aproximadamente» y el filtro de la vía general la rechazaba como cifra
exacta inventada. Una cifra que el usuario escribió (en la pregunta o en un
turno suyo anterior) está respaldada; una cifra nueva sin aproximador se sigue
rechazando.
"""

import asyncio

from app.schemas import ChatResponse
from app.schemas.api import ChatTurn
from app.services.chat_synthesis_service import ChatSynthesisService
from tests.test_chat_general_es import StubProvider, _db

_ANSWER = "Si aportas los 600 € este mes, tu saldo sube en 600 € más lo que varíe el mercado."
_FALLBACK = "No puedo responderte con fuentes"


def _ask(text, question, history=None):
    return asyncio.run(
        ChatSynthesisService(StubProvider(text)).synthesize_general(
            question=question, baseline=ChatResponse(answer="", sources=[]), db=_db(), history=history
        )
    )


def test_number_from_the_question_is_not_invented():
    result = _ask(_ANSWER, "¿Y si este mes aporto los 600 € del plan, cuánto tendría?")
    assert _FALLBACK not in result.answer
    assert "600 €" in result.answer


def test_number_from_an_earlier_user_turn_is_not_invented():
    history = [
        ChatTurn(role="user", content="Mi plan es aportar 600 € al mes"),
        ChatTurn(role="assistant", content="Vale."),
    ]
    result = _ask(_ANSWER, "¿Y si lo hago este mes?", history)
    assert _FALLBACK not in result.answer


def test_a_new_exact_number_is_still_rejected():
    result = _ask(
        "Si aportas este mes tendrás 4.837 € en total.", "¿Y si este mes aporto los 600 € del plan?"
    )
    assert "4.837" not in result.answer


def test_assistant_turns_do_not_ground_numbers():
    history = [ChatTurn(role="assistant", content="Tendrás 4.837 € en total.")]
    result = _ask("Si aportas este mes tendrás 4.837 € en total.", "¿Seguro?", history)
    assert "4.837" not in result.answer
