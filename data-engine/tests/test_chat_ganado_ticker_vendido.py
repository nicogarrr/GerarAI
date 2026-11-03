"""Chat: «¿cuánto he ganado con KO?» tras venderla entera.

Contestaba «No tienes ninguna posición abierta en KO: no hay rentabilidad
guardada que contar», aunque la venta (+180 €) estaba en tus operaciones y en
el informe fiscal. Ahora dice lo realizado con esas ventas (mismo FIFO del
informe, en euros); «este año»/«2025» acotan el ejercicio. Solo del tenant.
"""

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401

KO = ("Ya no tienes posición abierta en KO. Realizado con tus ventas guardadas de KO: +180,00 € "
      "(1 venta: 1 oct 2026; en euros, FIFO como en el informe fiscal).")


def test_realized_of_a_closed_ticker():
    for question in ("¿Cuánto he ganado con KO?", "¿cuánto he ganado con KO este año?",
                     "¿qué rentabilidad he sacado de KO?"):
        resp = _ask(_db(), question)
        assert resp.llm_trace["path"] == "portfolio_performance"
        assert resp.llm_trace["provider_calls"] == 0
        assert resp.answer == KO


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
