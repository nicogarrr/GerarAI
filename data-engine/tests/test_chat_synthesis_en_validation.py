"""Ramas de validacion de prosa EN y reloj de Tokio de chat_synthesis_service."""

import re

import pytest

from app.services import chat_synthesis_service as svc
from app.services.chat_synthesis_service import (
    _clock_context,
    _prose_answer_valid,
)
from app.services.chat_synthesis_service import (
    _inferred_general_text_valid_en as valid_en,
)

OK = "Free cash flow is the cash left after capital spending."


def test_prose_answer_en_accepts_english_and_rejects_spanish_text():
    assert _prose_answer_valid(OK, expected_language="en") is True
    spanish = "La empresa tiene una deuda neta de la compañía y el margen de la caja"
    assert _prose_answer_valid(spanish, expected_language="en") is False
    assert _prose_answer_valid(spanish, expected_language="es") is True


def test_prose_answer_es_rejects_english_text():
    english = "The company has a net debt of the firm and the margin of the cash flow"
    assert _prose_answer_valid(english, expected_language="es") is False


def test_clock_context_tokyo_only_with_hour_and_city():
    ctx = _clock_context("¿Qué hora es en Tokio?")
    assert ctx["timezone"] == "Asia/Tokyo" and ctx["place"] == "Tokio"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d\+09:00", ctx["local_time"])
    assert _clock_context("What hora is it in Tokyo?")["timezone"] == "Asia/Tokyo"
    assert _clock_context("¿Qué hora es en Madrid?") is None
    assert _clock_context("Háblame de Tokio") is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "See https://example.org for more",
        "x" * 8001,
        "Visit example.com/page for the details",
        "The token is [broken] here",
        "The company reported strong results",
        "According to the source, margins grew",
        "Revenue was 1,234.56 last year",
        "Esto es una frase con la empresa y la deuda de la compañía en el margen",
        "Review my portfolio holdings today",
    ],
)
def test_en_validator_rejects(text):
    assert valid_en(text) is False


def test_en_validator_rejects_secret_like_token(monkeypatch):
    monkeypatch.setattr(svc, "_SECRET_RE", re.compile("sk-secret"))
    assert valid_en("The key is sk-secret") is False


def test_en_validator_accepts_plain_and_non_quantitative():
    assert valid_en(OK) is True
    assert valid_en("Revenue was 5,000 million", quantitative=False) is True


def test_en_validator_placeholders():
    assert valid_en("Margin is [some note] today", allow_placeholders=True, quantitative=False) is True
    assert valid_en("Margin is [INFERIDO] today", allow_placeholders=True, quantitative=False) is False
    assert valid_en("Margin is [revenue growth] today", allow_placeholders=True, quantitative=False) is False
    assert valid_en("Margin is [some note] today", allow_placeholders=False) is False


def test_en_validator_named_attribution():
    buffett = frozenset({"buffett"})
    according = "According to Buffett, patience matters."
    assert valid_en(according) is False
    assert valid_en(according, allow_named_attribution=True, allowed_investors=buffett) is True
    opinion = "Buffett dice que patience matters"
    assert valid_en(opinion, quantitative=False) is False
    assert valid_en(opinion, quantitative=False, allow_named_attribution=True, allowed_investors=buffett) is True
    other = "Munger dice que patience matters"
    assert valid_en(other, quantitative=False, allow_named_attribution=True, allowed_investors=buffett) is False


def test_en_validator_portfolio_claims_flag():
    text = "Your portfolio is concentrated."
    assert valid_en(text, quantitative=False) is False
    assert valid_en(text, quantitative=False, allow_portfolio_claims=True) is True


@pytest.mark.parametrize(
    "text,grounded,expected",
    [
        ("Revenue was 250 last quarter", frozenset(), False),
        ("Revenue was about 250 last quarter", frozenset(), True),
        ("Revenue was 250 last quarter", frozenset({"250"}), True),
        ("It started in 2019 and grew", frozenset(), True),
        ("It grew from 2019 to 2021", frozenset(), True),
        ("It grew to about 8000 million", frozenset(), True),
        ("Revenue was about 5 to 7 percent", frozenset(), True),
        ("Revenue was about 5 and 7 percent", frozenset(), False),
        ("Revenue was 5 to 7 percent", frozenset(), False),
        ("1. Revenue was about 250\n2. Margin was about 10", frozenset(), True),
        ("Revenue was 250", frozenset({"999"}), False),
    ],
)
def test_en_validator_quantitative_branches(text, grounded, expected):
    assert valid_en(text, grounded_numbers=grounded) is expected


def test_en_validator_named_attribution_skips_clauses_without_magnitude():
    assert valid_en("Buffett wrote in 1990 about patience", allow_named_attribution=True,
                    allowed_investors=frozenset({"buffett"})) is True


def test_flatten_text_walks_nested_values_and_ignores_non_text():
    value = {"a": "uno", "b": ["dos", ("tres", 4)], "c": {"d": "cuatro"}, "e": None}
    assert svc._flatten_text(value) == ["uno", "dos", "tres", "cuatro"]
    assert svc._flatten_text(7) == []


def _baseline(text="Ingresos de 100 millones"):
    from types import SimpleNamespace

    section = SimpleNamespace(model_dump=lambda: {"body": text})
    return SimpleNamespace(sections=[section], sources=["fuente"])


def test_reject_untrusted_output_blocks_secrets_links_and_ungrounded_figures():
    base = _baseline()
    svc._reject_untrusted_output({"answer": "Sin cifras.", "sections": []}, base, "pregunta")
    with pytest.raises(ValueError, match="Secret-like"):
        svc._reject_untrusted_output({"answer": "clave sk-abcdefghijklmnop1234", "sections": []}, base, "q")
    with pytest.raises(ValueError, match="External link"):
        svc._reject_untrusted_output(
            {"answer": "ok", "sections": [{"body": "mira https://x.test"}, "no-dict"]}, base, "q"
        )
    with pytest.raises(ValueError, match="Ungrounded number"):
        svc._reject_untrusted_output({"answer": "Ingresos de 777 millones", "sections": []}, base, "q")
