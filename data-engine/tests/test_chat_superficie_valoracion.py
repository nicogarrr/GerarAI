"""Chat (superficie de valoración): margen de seguridad directo, unidad del
precio (GBX/GBP) y etiquetas en castellano de los inputs ausentes del motor.

Hallazgos de la revisión de la batería de valoración (2026-11-04):

1. «¿Está barata KKR?» / «¿margen de seguridad de POOL?» con tesis publicada y
   cierre guardado nunca daban la cifra: volcaban precio y tesis por separado.
   Ahora responden (valor − precio) / valor con su base, o el porqué del N/D.
2. El precio del volcado de empresa rotulaba el close con la divisa de la
   compañía: 4.200 peniques (GBX) salían como «4.200,00 GBP» (x100). La unidad
   la declara la fuente (quote_currency); sin unidad verificable no se muestra
   cifra con una divisa supuesta.
3. «El motor no tiene valoración de X: faltan holding_company_discount,
   segment_*_operating_metric…» volcaba claves internas en inglés. Ahora son
   etiquetas públicas en castellano.
4. «¿Está barata PLTR?» sin ficha de PLTR volcaba el ranking de la watchlist
   sin decir que PLTR no existe en GerarAI; lo contesta la ruta de ticker
   desconocido.
"""

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.i18n import reset_language_scope, set_language_scope
from app.models import Company, MarketPrice
from app.schemas.api import ChatTurn
from app.services.chat_service import ChatService
from tests.cerebro_seed import seeded_session


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _ask(question, *, db=None, ticker=None, history=None):
    token = set_language_scope("es")
    try:
        db = db or seeded_session()
        db.info["language"] = "es"
        return asyncio.run(
            ChatService(provider=_NoLLM()).answer(db, question, "portfolio", ticker, history=history or [])
        )
    finally:
        reset_language_scope(token)


def _add_quote(db, ticker, close, quote_currency, day=date(2026, 10, 25)):
    company_id = db.scalars(select(Company.id).where(Company.ticker == ticker)).first()
    db.add(MarketPrice(company_id=company_id, date=day, close=Decimal(close), quote_currency=quote_currency))
    db.commit()
    return db


def _followup_cgeo(db):
    first = _ask("¿Cuál es el valor justo de CGEO.L?", db=db, ticker="CGEO.L")
    history = [
        ChatTurn(role="user", content="¿Cuál es el valor justo de CGEO.L?"),
        ChatTurn(role="assistant", content=first.answer),
    ]
    return _ask("¿Y su valor justo?", db=db, history=history)


def test_engine_missing_inputs_are_spanish_public_labels():
    response = _ask("¿Cuál es el valor justo de CGEO.L?", ticker="CGEO.L")
    assert "descuento de sociedad holding" in response.answer
    assert "deuda neta" in response.answer
    assert "segmento" in response.answer
    assert "holding_company_discount" not in response.answer
    assert "segment_" not in response.answer
    assert "shares_diluted" not in response.answer


def test_price_without_verifiable_unit_is_not_shown_with_an_assumed_currency():
    response = _followup_cgeo(seeded_session())
    assert "sin unidad verificable" in response.answer
    assert "4.200,00 GBP" not in response.answer


def test_declared_pence_quote_is_shown_in_pounds():
    db = _add_quote(seeded_session(), "CGEO.L", "4200", "GBX")
    response = _followup_cgeo(db)
    assert "42,00 GBP" in response.answer
    assert "4.200,00 GBP" not in response.answer


def test_cheap_question_answers_the_margin_with_its_basis():
    response = _ask("¿Está barata KKR?")
    assert "+25,0 %" in response.answer
    assert "(valor − precio) / valor" in response.answer
    assert "$160.00" in response.answer
    assert "$120.00" in response.answer
    assert "no una cotización en directo" in response.answer


def test_margin_of_safety_question_gives_the_figure():
    response = _ask("¿Cuál es el margen de seguridad de POOL?")
    assert "+25,0 %" in response.answer


def test_pence_quote_is_converted_before_crossing_with_a_gbp_fair_value():
    db = _add_quote(seeded_session(), "CGEO.L", "4200", "GBX")
    response = _ask("¿Cuál es el margen de seguridad de CGEO.L?", db=db)
    assert "+1,3 %" in response.answer
    assert "42,00 GBP" in response.answer


def test_margin_is_not_calculated_across_currencies_without_verified_fx():
    db = _add_quote(seeded_session(), "KKR", "120", "GBP")
    response = _ask("¿Está barata KKR?", db=db)
    assert "no los cruzo sin un tipo de cambio verificado" in response.answer
    assert "+25,0 %" not in response.answer


def test_cheap_question_without_fair_value_says_why_not():
    response = _ask("¿Está barata CPT?")
    assert "no hay valor justo guardado" in response.answer


def test_cheap_question_with_unknown_ticker_does_not_dump_the_watchlist():
    response = _ask("¿Está barata PLTR?")
    assert "No tengo «PLTR»" in response.answer
    assert "watchlist" not in response.answer


def test_general_watchlist_ranking_is_untouched():
    response = _ask("¿Qué está barato de mi watchlist?")
    assert "KKR" in response.answer
    assert "+25,0 %" in response.answer
