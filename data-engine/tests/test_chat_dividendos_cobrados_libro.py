"""Chat, «¿cuánto he cobrado en dividendos este año?» con los cobros de tu libro.

La respuesta de cartera lee los dividendos DECLARADOS por el proveedor (×
acciones de hoy). Sin ellos contestaba «No hay dividendos guardados de tus
posiciones para 2026» aunque tus operaciones guardadas (p. ej. el CSV de IBKR)
tuvieran el cobro, y el bloque fiscal del mismo chat lo contaba (3,74 € brutos).
Ahora, si el proveedor no tiene nada, dice lo que consta en tu libro, en euros
como el informe fiscal. Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401


@pytest.mark.parametrize(
    "question", ["¿Cuánto he cobrado en dividendos este año?", "¿cuántos dividendos he cobrado este año?"]
)
def test_ledger_dividends_when_the_provider_has_none(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_dividends"
    assert resp.llm_trace["provider_calls"] == 0
    assert [line for line in resp.answer.splitlines() if line] == [
        "En tus operaciones guardadas de 2026 constan 3,74 EUR de dividendos brutos cobrados y 0,56 EUR de "
        "retención en origen (en euros, como en el informe fiscal).",
        "El proveedor no tiene dividendos declarados guardados de tus posiciones abiertas para 2026.",
    ]


def test_year_without_ledger_dividends_unchanged():
    resp = _ask(_db(), "¿Cuánto he cobrado en dividendos en 2025?")
    assert resp.answer == "No hay dividendos guardados de tus posiciones para 2025. No he consultado el proveedor en directo."


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánto he cobrado en dividendos este año?")
    assert "3,74" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How much did I collect in dividends this year?")
    finally:
        get_settings.cache_clear()
    assert [line for line in resp.answer.splitlines() if line][0] == (
        "In your saved trades for 2026: 3.74 EUR of gross dividends received and 0.56 EUR withheld at source "
        "(in euros, as in the tax report)."
    )
