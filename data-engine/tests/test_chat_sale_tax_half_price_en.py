"""IRPF de «vender la mitad a un precio» escrito en inglés (prueba real 2026-11-03).

«tax if I sold half my Apple shares at $280» calculaba la mitad pero con el
valor guardado, sin decirlo: «half my» no se traducía a «la mitad de mis» y el
precio dado se perdía. Y con Ajustes en español la misma pregunta en inglés ni
llegaba al IRPF (salía la ficha de la empresa).
"""

from app.core.i18n import reset_language_scope, set_language_scope
from tests.test_chat_english_sale_tax import _ask, _flag, _session  # noqa: F401


def _q(language, question):
    token = set_language_scope(language)
    session = _session(language)
    try:
        return _ask(session, question)
    finally:
        session.close()
        reset_language_scope(token)


def test_half_at_a_price_uses_the_price_in_english():
    resp = _q("en", "How much tax would I pay if I sold half my UBER shares at 95 €?")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.answer.startswith(
        "If you sold 15 of your 30 UBER shares today (data as of Oct 30, 2026): value 1,425.00 €, "
        "cost 750.00 € (sale price given: 95.00 €), a gain of 675.00 €."
    )


def test_half_of_my_shares_at_a_price():
    resp = _q("en", "What would my capital gains tax be if I sold half of my UBER shares at 90 €?")
    assert "value 1,350.00 €" in resp.answer
    assert "(sale price given: 90.00 €)" in resp.answer


def test_usd_price_without_rate_never_falls_back_to_the_saved_value():
    resp = _q("en", "tax if I sold half my UBER shares at $80")
    assert resp.answer.startswith("You gave a sale price in USD, but today's exchange rate is missing")


def test_english_question_with_spanish_settings_reaches_the_irpf_path():
    resp = _q("es", "tax if I sold half my UBER shares at 95 €")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.answer.startswith(
        "Si vendieras hoy 15 de tus 30 acciones de UBER (datos a 30 oct 2026): valor 1.425,00 €, "
        "coste 750,00 € (precio de venta indicado: 95,00 €), ganancia de 675,00 €."
    )


def test_spanish_question_is_unchanged():
    resp = _q("es", "¿Cuánto IRPF pagaría si vendo la mitad de UBER a 95 €?")
    assert "valor 1.425,00 €" in resp.answer
