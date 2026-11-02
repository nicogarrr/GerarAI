"""Cerebro (datos de tu cuenta): preguntas que iban al bloque equivocado.

- «¿Cuánto efectivo tiene Apple en caja?» habla de la caja de una empresa: no
  es tu efectivo (antes contestaba «No tienes efectivo guardado»).
- «How much did my portfolio change today?» y «¿Hoy cuánto he ganado o
  perdido?» son el cambio de hoy de tu cartera (antes no entraban).
Solo lectura; datos sembrados como el resto de tests del Cerebro.
"""

from __future__ import annotations

import pytest

from app.services.brain_account_tools import answer_account_question
from tests.cerebro_seed import seeded_session


def _answer(question: str) -> str | None:
    response = answer_account_question(seeded_session(), question)
    return None if response is None else response.answer


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuánto efectivo tiene Apple en caja?",
        "¿Cuánta caja tiene Microsoft?",
        "How much cash does Apple have?",
    ],
)
def test_la_caja_de_una_empresa_no_es_tu_efectivo(question):
    assert _answer(question) is None


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuánto efectivo tengo?",
        "¿Cuánta caja tiene mi cartera?",
        "How much cash do I have?",
        "my cash balance",
    ],
)
def test_tu_efectivo_sigue_contestandose(question):
    answer = _answer(question)
    assert answer is not None and "efectivo" in answer.lower()


@pytest.mark.parametrize(
    "question",
    [
        "How much did my portfolio change today?",
        "How did my portfolio move today?",
        "¿Hoy cuánto he ganado o perdido?",
    ],
)
def test_cambio_de_hoy_de_tu_cartera(question):
    answer = _answer(question)
    assert answer is not None and "histórico diario" in answer


def test_la_cotizacion_de_hoy_de_una_empresa_sigue_fuera():
    assert _answer("How much did UBER change today?") is None
