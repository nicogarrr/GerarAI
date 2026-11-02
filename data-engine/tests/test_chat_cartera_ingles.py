"""Chat: «how is my portfolio doing?» en inglés sin modelo sale en inglés.

Antes, en inglés, si el modelo fallaba (o no había modelo) la respuesta
determinista de la cartera salía en castellano: «Tu cartera (/portfolio): -
1 posiciones; divisa base EUR… peso… valor…» o «No tienes posiciones
guardadas…». El contexto que recibe el modelo no cambia. Solo lectura y solo
del tenant.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import reset_language_scope, set_language_scope
from app.models.entities import Base, Company, Portfolio, Position
from app.services.chat_service import ChatService
from app.services.personal_answer import answer_personal_question, detect_personal_intent
from app.services.user_context import build_user_context


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _db(with_positions=True):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant, ticker in ((1, "KO"), (2, "TSLA")):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="consumer",
                          valuation_model="unassigned", currency="USD", sector="Consumer")
        db.add(company)
        db.flush()
        db.info["tenant_id"] = tenant
        portfolio = Portfolio(tenant_id=tenant, name="Principal", base_currency="EUR", is_default=True)
        db.add(portfolio)
        db.flush()
        if with_positions:
            db.add(Position(tenant_id=tenant, portfolio_id=portfolio.id, company_id=company.id,
                            quantity=Decimal("10"), average_cost=Decimal("50"), market_price=Decimal("60"),
                            market_value=Decimal("600"), market_value_base=Decimal("550"),
                            cost_basis_base=Decimal("500"), unrealized_pnl_base=Decimal("50"),
                            currency="USD", base_currency="EUR", as_of=datetime(2026, 10, 30, tzinfo=UTC)))
        db.commit()
    db.info["tenant_id"] = 1
    return db


@pytest.fixture()
def english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question, english=True):
    if english:
        db.info["language"] = "en"
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def _fallback(db, question="how is my P&L in my portfolio?"):
    intent = detect_personal_intent(question)
    assert intent is not None and intent.kind == "cartera"
    token = set_language_scope("en")
    try:
        resp = asyncio.run(answer_personal_question(db, question, intent, None, dca_reader=lambda *_a: {}))
    finally:
        reset_language_scope(token)
    assert resp is not None
    return resp


def test_english_portfolio_fallback_in_english(english):
    # Con posiciones, la mayoría de preguntas en inglés van a portfolio_overview
    # (ya en inglés); esta es la respuesta sin modelo de la ruta personal.
    resp = _fallback(_db())
    lines = resp.answer.splitlines()
    assert lines[0] == "Your portfolio (/portfolio):"
    assert lines[1].startswith("- 1 position; base currency EUR; data as of Oct 30, 2026. Total value 550.00 EUR.")
    assert "Unrealized P&L +50.00 EUR (+10.0% on cost)." in lines[1]
    assert lines[2].startswith("- KO (KO Inc), weight 100.0%, value 550.00 EUR, ")
    assert lines[-1] == "- Weight by sector: Consumer 100.0%."
    for spanish in ("Tu cartera", "posiciones", "divisa base", "peso", "valor ", "precio", "nivel DCA", "Peso por"):
        assert spanish not in resp.answer


def test_english_empty_portfolio(english):
    resp = _ask(_db(with_positions=False), "how is my portfolio doing?")
    assert resp.answer.startswith("You have no saved positions in your portfolio (/portfolio).")
    assert "No tienes" not in resp.answer


def test_model_context_stays_spanish(english):
    db = _db()
    db.info["language"] = "en"
    ctx = build_user_context(db, sections=("cartera",), dca_reader=lambda *_a: {})
    assert ctx is not None
    rendered = ctx.render()
    assert "1 posiciones; divisa base EUR" in rendered
    assert "base currency" not in rendered and "weight" not in rendered


def test_user_b_never_sees_user_a(english):
    db = _db()
    db.info["tenant_id"] = 2
    resp = _fallback(db)
    assert "TSLA" in resp.answer and "KO" not in resp.answer


def test_spanish_unchanged():
    db = _db()
    intent = detect_personal_intent("¿cómo va el P&L de mi cartera?")
    assert intent is not None and intent.kind == "cartera"
    resp = asyncio.run(answer_personal_question(db, "¿cómo va el P&L de mi cartera?", intent, None,
                                                dca_reader=lambda *_a: {}))
    assert resp is not None
    assert resp.answer.splitlines()[0] == "Tu cartera (/portfolio):"
    assert "- 1 posiciones; divisa base EUR" in resp.answer
