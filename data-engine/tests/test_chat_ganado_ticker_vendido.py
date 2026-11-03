"""Chat: «¿cuánto he ganado con KO?» tras venderla entera.

Contestaba «No tienes ninguna posición abierta en KO: no hay rentabilidad
guardada que contar», aunque la venta (+180 €) estaba en tus operaciones y en
el informe fiscal. Ahora dice lo realizado con esas ventas (mismo FIFO del
informe, en euros); «este año»/«2025» acotan el ejercicio. Solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401

KO = ("Ya no tienes posición abierta en KO. Realizado con tus ventas guardadas de KO: +180,00 € "
      "(1 venta: 1 oct 2026; en euros, FIFO como en el informe fiscal).")


def test_realized_of_a_closed_ticker():
    for question in ("¿Cuánto he ganado con KO?", "¿qué rentabilidad he sacado de KO?", "¿cuánto gané con KO?"):
        resp = _ask(_db(), question)
        assert resp.llm_trace["path"] == "portfolio_performance"
        assert resp.llm_trace["provider_calls"] == 0
        assert resp.answer == KO
    resp = _ask(_db(), "¿cuánto he ganado con KO este año?")
    assert resp.answer == KO.replace("Realizado con", "Realizado en 2026 con")


@pytest.mark.parametrize("question", ["¿cuánto gané con KO en 2026?", "¿cuánto he ganado con KO en 2026?"])
def test_ticker_with_a_year(question):
    """Con un año la pregunta es fiscal: con empresa caía al volcado de la empresa
    («Todavía no tengo hechos financieros fiables…»). Ahora, lo realizado ese año."""
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer == (
        "Realizado en 2026 con tus ventas guardadas de KO: +180,00 € "
        "(1 venta: 1 oct 2026; en euros, FIFO como en el informe fiscal)."
    )


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("¿cuánto gané con KO en 2025?", "En 2025 no hay ventas de KO en tus operaciones guardadas."),
        ("¿cuánto he ganado con KO el año pasado?", "En 2025 no hay ventas de KO en tus operaciones guardadas."),
        # Con posición abierta: lo realizado ese año (UBER vendió 10 en 2025), no lo latente de hoy.
        ("¿cuánto gané con UBER en 2026?", "En 2026 no hay ventas de UBER en tus operaciones guardadas."),
    ],
)
def test_ticker_with_a_year_without_sales(question, answer):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert resp.answer == answer


def test_open_position_with_a_year_is_realized_not_latent():
    resp = _ask(_db(), "¿cuánto gané con UBER en 2025?")
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert resp.answer.startswith("Realizado en 2025 con tus ventas guardadas de UBER: +")
    assert "+60 %" not in resp.answer


def test_year_without_ticker_still_goes_to_the_year_block():
    assert _ask(_db(), "¿cuánto gané en 2026?").llm_trace["path"] == "account_year_gains"


def test_year_without_sales_of_that_ticker():
    from sqlalchemy import select

    from app.models import Company
    from app.services.brain_account_tools import realized_line_for_closed_ticker

    db = _db()
    ko = db.scalar(select(Company).where(Company.ticker == "KO"))
    assert realized_line_for_closed_ticker(db, 1, ko.id, "KO", "¿cuánto gané con KO el año pasado?", False) == (
        "En 2025 no hay ventas de KO en tus operaciones guardadas."
    )


def test_never_held_unchanged_and_tenant_isolated():
    resp = _ask(_db(), "¿cuánto he ganado con AAPL?")
    assert resp.answer == "No tienes ninguna posición abierta en AAPL: no hay rentabilidad guardada que contar."
    db = _db()
    db.info["tenant_id"] = 2
    assert "+180" not in _ask(db, "¿cuánto he ganado con KO?").answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How much did I make on KO?")
    finally:
        get_settings.cache_clear()
    assert resp.answer == (
        "You no longer have an open position in KO. Realized with your saved sales of KO: +180.00 € "
        "(1 sale: Oct 1, 2026; in euros, FIFO as in the tax report)."
    )
