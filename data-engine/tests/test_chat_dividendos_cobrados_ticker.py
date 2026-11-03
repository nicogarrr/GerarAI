"""Chat: «¿cuánto cobré de dividendos de MSFT?» mira lo cobrado en tu libro.

#4375 arregló «¿cuánto he cobrado en dividendos?» (sin empresa): si el
proveedor no tenía dividendos declarados, contaba lo cobrado en tus
operaciones guardadas. Con una empresa nombrada seguía diciendo «No hay
dividendos guardados de tus posiciones para 2026» aunque el libro tuviera el
cobro de MSFT (y el informe fiscal lo contara). Ahora da lo de esa empresa;
y si ya la vendiste, lo cobrado mientras la tenías. Solo del tenant.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import Company, Transaction
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401

MSFT = ("En tus operaciones guardadas de 2026 constan 3,74 EUR de dividendos brutos cobrados de MSFT "
        "y 0,56 EUR de retención en origen (en euros, como en el informe fiscal).")


def test_named_ticker_uses_the_ledger():
    for question in ("¿Cuánto cobré de dividendos de MSFT?", "¿cuántos dividendos he cobrado de MSFT este año?"):
        resp = _ask(_db(), question)
        assert resp.llm_trace["path"] == "portfolio_dividends"
        assert resp.llm_trace["provider_calls"] == 0
        assert resp.answer.splitlines()[0] == MSFT
        assert "El proveedor no tiene dividendos declarados guardados de MSFT para 2026." in resp.answer


def test_other_ticker_and_other_year_have_none():
    assert _ask(_db(), "¿cuánto cobré de dividendos de UBER?").answer == (
        "No hay dividendos guardados de UBER para 2026. No he consultado el proveedor en directo.")
    assert _ask(_db(), "¿cuánto cobré de dividendos de MSFT en 2025?").answer == (
        "No hay dividendos guardados de MSFT para 2025. No he consultado el proveedor en directo.")


def test_sold_ticker_keeps_what_it_paid():
    db = _db()
    ko = db.scalar(select(Company).where(Company.ticker == "KO"))
    db.add(Transaction(tenant_id=1, company_id=ko.id, trade_date=date(2026, 4, 1), action="dividend",
                       quantity=Decimal("1"), price=Decimal("10"), fees=Decimal("0"), currency="USD"))
    db.commit()
    resp = _ask(db, "¿cuánto cobré de dividendos de KO?")
    assert resp.answer == ("En tus operaciones guardadas de 2026 constan 9,00 EUR de dividendos brutos cobrados de KO "
                           "y 0,00 EUR de retención en origen (en euros, como en el informe fiscal).")


def test_tenant_isolation():
    db = _db()
    db.info["tenant_id"] = 2
    assert "3,74" not in _ask(db, "¿cuánto cobré de dividendos de MSFT?").answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How much did I receive in dividends from MSFT?")
    finally:
        get_settings.cache_clear()
    assert resp.answer.splitlines()[0] == (
        "In your saved trades for 2026: 3.74 EUR of gross dividends received from MSFT and "
        "0.56 EUR withheld at source (in euros, as in the tax report).")
