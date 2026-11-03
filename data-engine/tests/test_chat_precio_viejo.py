"""Precio viejo de una posición avisado en el chat (prueba real 2026-11-03).

Con un precio guardado de feb 2024 (ULVR.L), el resumen de cartera decía «con
datos a 30 oct 2026» (la fecha más nueva) y la posición se presentaba como de
hoy, sin avisar. Ahora la línea de esa posición lleva su fecha y la pregunta
por esa posición avisa.
"""

import asyncio
from datetime import date

import pytest

from app.core.i18n import reset_language_scope, set_language_scope
from app.models.entities import Company, Position
from app.services.chat_service import ChatService
from tests.test_chat_english_sale_tax import _flag, _session  # noqa: F401


def _ask(language, question, stale=True):
    token = set_language_scope(language)
    db = _session(language)
    try:
        if stale:
            asts = db.query(Company).filter_by(ticker="ASTS").one()
            db.query(Position).filter_by(company_id=asts.id).one().as_of = date(2024, 2, 1)
            db.commit()
        return asyncio.run(ChatService().answer(db, question, "portfolio", None)).answer
    finally:
        db.close()
        reset_language_scope(token)


def test_overview_marks_the_stale_position():
    answer = _ask("es", "¿Qué tengo en mi cartera?")
    line = next(line for line in answer.splitlines() if line.startswith("- ASTS"))
    assert line.endswith("(precio de 1 feb 2024, desactualizado)")
    uber = next(line for line in answer.splitlines() if line.startswith("- UBER"))
    assert "desactualizado" not in uber


def test_overview_in_english():
    answer = _ask("en", "What do I have in my portfolio?")
    line = next(line for line in answer.splitlines() if line.startswith("- ASTS"))
    assert line.endswith("(price from Feb 1, 2024, out of date)")


@pytest.mark.parametrize(("language", "question", "warning"), [
    ("es", "¿Cuántas acciones tengo de ASTS?", "Ojo: ese precio es del 1 feb 2024, más antiguo que el del resto de tu cartera (30 oct 2026)"),
    ("en", "How many ASTS shares do I have?", "Note: that price is from Feb 1, 2024, older than the rest of your portfolio (Oct 30, 2026)"),
])
def test_position_answer_warns(language, question, warning):
    assert warning in _ask(language, question)


def test_fresh_portfolio_has_no_warning():
    answer = _ask("es", "¿Qué tengo en mi cartera?", stale=False)
    assert "desactualizado" not in answer
    assert "Ojo:" not in _ask("es", "¿Cuántas acciones tengo de ASTS?", stale=False)
