"""Chat: «¿cuántas ventas he hecho este año?» / «how many sales did I make?» con un recuento.

Antes la pregunta caía al modelo general («No puedo responderte con fuentes…»):
el recuento de #4300 solo reconocía «operaciones/compras» y las ventas del año
solo salían con «¿qué he vendido…?». Ahora cuenta solo tus ventas guardadas,
por año y, con varias carteras, por cartera. Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_cuantas_operaciones import _ask, _db, _today  # noqa: F401


@pytest.mark.parametrize(
    "question",
    ["¿Cuántas ventas he hecho este año?", "cuantas ventas llevo este año", "¿Cuántas ventas hice en 2026?"],
)
def test_sells_this_year(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_trade_count"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "En 2026 tienes 1 venta guardada.",
        "Cuento solo ventas; no compras, dividendos ni movimientos de efectivo.",
    ]


def test_sells_all_years_and_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuántas ventas he hecho?")
    assert resp.answer.splitlines() == [
        "Tienes 1 venta guardada.",
        "Cuento solo ventas; no compras, dividendos ni movimientos de efectivo.",
    ]
    db.info["tenant_id"] = 1
    assert _ask(db, "¿Cuántas ventas he hecho este año?").answer.splitlines()[0] == "En 2026 tienes 1 venta guardada."


def test_no_sells_in_period():
    resp = _ask(_db(), "¿cuántas ventas he hecho en 2025?")
    assert resp.llm_trace["path"] == "account_trade_count"
    assert resp.answer == "No hay ventas guardadas de 2025."


def test_no_sells_at_all():
    resp = _ask(_db(empty=True), "¿cuántas ventas he hecho?")
    assert resp.answer == "No tienes ventas guardadas."


def test_company_sales_are_not_my_sales():
    resp = _ask(_db(), "¿Cuántas ventas tiene KO?")
    assert (resp.llm_trace or {}).get("path") != "account_trade_count"


@pytest.mark.parametrize("question", ["How many sales did I make this year?", "how many sells have I made this year?"])
def test_english(monkeypatch, question):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_trade_count"
    assert resp.answer.splitlines() == [
        "In 2026 you have 1 saved sell.",
        "Counting sells only; not buys, dividends or cash movements.",
    ]
