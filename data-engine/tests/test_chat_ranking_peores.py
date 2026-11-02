"""Chat, ranking de posiciones: «mis peores posiciones» y «mis 3 peores».

«¿Cuáles son mis peores posiciones?» contestaba «La que MEJOR va…» y ordenaba
de mejor a peor: solo «peor» (singular) contaba como pedir las peores. Con una
cifra («mis 3 peores posiciones», «my two best stocks») la pregunta ni se
reconocía y caía al modelo general. Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_posiciones_perdidas import _ask, _db


def test_plural_worst_puts_the_worst_first():
    resp = _ask(_db(), "¿Cuáles son mis peores posiciones?")
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.answer.splitlines()[:3] == [
        "La que peor va sobre su coste: KO -15,4 % (-100,00 €).",
        "Todas tus posiciones por rentabilidad sobre el coste de compra (datos a 30 oct 2026):",
        "1. KO -15,4 % (-100,00 €)",
    ]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "¿Cuáles son mis 2 peores posiciones?",
            [
                "Tus 2 peores posiciones por rentabilidad sobre el coste de compra (datos a 30 oct 2026):",
                "1. KO -15,4 % (-100,00 €)",
                "2. ITX -10,0 % (-20,00 €)",
                "Rentabilidad simple desde la compra, sin dividendos.",
            ],
        ),
        (
            "mis dos mejores acciones",
            [
                "Tus 2 mejores posiciones por rentabilidad sobre el coste de compra (datos a 30 oct 2026):",
                "1. TSLA +50,0 % (+500,00 €)",
                "2. ITX -10,0 % (-20,00 €)",
                "Rentabilidad simple desde la compra, sin dividendos.",
            ],
        ),
    ],
)
def test_count_lists_only_that_many(question, expected):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == expected


def test_english_count(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "What are my 2 worst positions?")
    finally:
        get_settings.cache_clear()
    assert resp.answer.splitlines()[:3] == [
        "Your 2 worst positions by return on purchase cost (data as of Oct 30, 2026):",
        "1. KO -15.4% (-100.00 €)",
        "2. ITX -10.0% (-20.00 €)",
    ]


def test_count_with_a_ticker_is_not_a_ranking():
    resp = _ask(_db(), "¿son KO e ITX mis 2 peores posiciones?")
    assert (resp.llm_trace or {}).get("path") != "account_return_ranking"
