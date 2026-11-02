"""Chat, recuento y lista de operaciones: el periodo pedido con nombre de mes,
«el año pasado» o «este trimestre».

Antes solo se leían «este mes», «el mes pasado» y un año: «¿cuántas ventas he
hecho en octubre?» contestaba «Tienes 1 venta guardada» con la venta de MARZO
(todas las de siempre, sin decirlo), igual con «el año pasado» y «este
trimestre», y «en marzo de 2026» contaba todo 2026. «¿Cuál fue mi última venta
este año?» listaba también las compras.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_cuantas_operaciones import _ask, _db, _today  # noqa: F401


@pytest.mark.parametrize(
    ("question", "first_line"),
    [
        ("¿Cuántas ventas he hecho en octubre?", "No hay ventas guardadas de octubre de 2026."),
        ("¿cuántas ventas he hecho en marzo?", "En marzo de 2026 tienes 1 venta guardada."),
        ("¿cuántas ventas he hecho el año pasado?", "No hay ventas guardadas de 2025."),
        ("¿cuántas ventas he hecho este trimestre?", "No hay ventas guardadas de octubre–diciembre de 2026."),
        ("¿cuántas ventas hice el trimestre pasado?", "No hay ventas guardadas de julio–septiembre de 2026."),
        (
            "¿cuántas operaciones hice en marzo de 2026?",
            "En marzo de 2026 tienes 1 operación de compraventa guardada: 1 venta.",
        ),
        (
            "¿cuántas operaciones he hecho el año pasado?",
            "En 2025 tienes 1 operación de compraventa guardada: 1 compra.",
        ),
    ],
)
def test_trade_count_reads_named_month_last_year_and_quarter(question, first_line):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_trade_count"
    assert resp.answer.splitlines()[0] == first_line


def test_december_asked_in_november_is_last_december():
    resp = _ask(_db(), "¿cuántas operaciones hice en diciembre?")
    assert resp.answer == "No hay compras ni ventas guardadas de diciembre de 2025."


def test_last_sell_this_year_lists_only_sells():
    resp = _ask(_db(), "¿cuál fue mi última venta este año?")
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.answer.splitlines() == [
        "Tus ventas guardadas de 2026:",
        "- 1 mar 2026: venta de 1 KO a 10,00 USD.",
    ]


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("How many sales did I make in October?", "There are no saved sells in October 2026."),
        ("how many trades did I make last year?", "In 2025 you have 1 saved buy or sell: 1 buy."),
    ],
)
def test_english(monkeypatch, question, answer):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.answer.splitlines()[0] == answer
