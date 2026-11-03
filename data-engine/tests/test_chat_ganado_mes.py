"""Chat: «¿cuánto gané en octubre?» da lo realizado y lo cobrado ese mes.

Antes iba al modelo general («No puedo responderte con fuentes ahora mismo…»):
el resumen de ganancias solo entendía un año. Ahora, con un mes («en octubre»,
«en junio de 2025», «el mes pasado»), las ventas y los dividendos cobrados de ese
mes, con el mismo FIFO en euros del informe fiscal. Lo latente no entra. Solo
del tenant, sin modelo.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401

FOOT = "En euros, como en el informe fiscal (borrador, no asesoría fiscal). Lo latente no es de un mes y no entra."


@pytest.mark.parametrize("question", ["¿Cuánto gané en octubre?", "¿cuánto he ganado en octubre?"])
def test_month_with_a_sale(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_month_gains"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "En octubre de 2026:",
        "- Realizado con ventas: +180,00 € (1 venta: KO).",
        "- Dividendos cobrados: ninguno ese mes.",
        FOOT,
    ]


def test_month_with_a_dividend_and_a_past_year():
    assert _ask(_db(), "¿cuánto gané en marzo?").answer.splitlines()[1:3] == [
        "- Realizado con ventas: nada, no hay ventas ese mes.",
        "- Dividendos cobrados: 3,74 € brutos, 0,56 € de retención en origen.",
    ]
    resp = _ask(_db(), "¿cuánto gané en junio de 2025?")
    assert resp.answer.splitlines()[:2] == ["En junio de 2025:", "- Realizado con ventas: +268,88 € (1 venta: UBER)."]


def test_last_month():
    # Hoy (fijado) es 30 oct 2026: el mes pasado es septiembre.
    assert _ask(_db(), "¿cuánto gané el mes pasado?").answer.splitlines()[:2] == [
        "En septiembre de 2026:", "- Realizado con ventas: nada, no hay ventas ese mes."]


def test_year_and_scenario_unchanged():
    assert _ask(_db(), "¿cuánto he ganado en 2026?").llm_trace["path"] == "account_year_gains"
    assert _ask(_db(), "¿cuánto gané en octubre si vendo UBER?").llm_trace["path"] != "account_month_gains"


def test_tenant_isolation():
    db = _db()
    db.info["tenant_id"] = 2
    assert "KO" not in _ask(db, "¿cuánto gané en octubre?").answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How much did I make in October?")
    finally:
        get_settings.cache_clear()
    assert resp.answer.splitlines()[:2] == ["In October 2026:", "- Realized from sales: +180.00 € (1 sale: KO)."]
