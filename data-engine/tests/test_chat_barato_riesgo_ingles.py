"""Chat: «what's cheap on my watchlist?» y el riesgo sin modelo, en inglés.

Antes, en inglés, si el modelo fallaba (o no había modelo) estas respuestas
salían enteras en castellano: «Lecturas guardadas…», «Aportación mensual…»,
«1 avisos abiertos…», «No hay margen positivo…», y el riesgo con la cartera
vacía «No tienes posiciones guardadas…». Mismo patrón que la watchlist
(#4268) y la cartera (#4277): ``lines_en`` en los bloques de plan y avisos.
El contexto que recibe el modelo no cambia. Solo lectura y solo del tenant.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import reset_language_scope, set_language_scope
from app.models.entities import Base, Company, InvestmentPlan, Portfolio, Position, ResearchAlert, WatchItem
from app.services.chat_service import ChatService
from app.services.personal_answer import answer_personal_question, detect_personal_intent
from app.services.user_context import build_user_context

SPANISH = (
    "Lecturas guardadas", "Aportación", "horizonte", "Asignación objetivo", "avisos abiertos",
    "reglas de aviso", "gravedad", "No hay margen", "Sin valor justo", "No tienes", "Concentración",
    "pesa ", "Peso por sector", "En pérdidas", "Avisos:", "Reglas del panel", "Tus datos",
)


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _db(with_positions=False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant, ticker, watched, amount in ((1, "KO", "MSFT", "300"), (2, "TSLA", "NVDA", "777")):
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
                            quantity=Decimal("10"), average_cost=Decimal("70"), market_price=Decimal("60"),
                            market_value=Decimal("600"), market_value_base=Decimal("550"),
                            cost_basis_base=Decimal("650"), unrealized_pnl_base=Decimal("-100"),
                            currency="USD", base_currency="EUR", as_of=datetime(2026, 10, 30, tzinfo=UTC)))
        db.add(WatchItem(tenant_id=tenant, symbol=watched))
        db.add(InvestmentPlan(tenant_id=tenant, status="active", monthly_contribution=Decimal(amount),
                              monthly_contribution_currency="EUR", horizon_years=10, start_date=date(2026, 1, 1),
                              target_allocations=[{"ticker": ticker, "weight": 50}]))
        db.add(ResearchAlert(tenant_id=tenant, company_id=company.id, status="open", title=f"{ticker} drops 5%",
                             message="m", severity="warning", alert_type="price", fingerprint=f"f{tenant}",
                             created_at=datetime(2026, 10, 31, 9, tzinfo=UTC)))
        db.commit()
    db.info["tenant_id"] = 1
    return db


@pytest.fixture()
def english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    db.info["language"] = "en"
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def _fallback(db, question, kind):
    intent = detect_personal_intent(question)
    assert intent is not None and intent.kind == kind
    token = set_language_scope("en")
    try:
        resp = asyncio.run(answer_personal_question(db, question, intent, None, dca_reader=lambda *_a: {}))
    finally:
        reset_language_scope(token)
    assert resp is not None
    return resp


def _no_spanish(text):
    for word in SPANISH:
        assert word not in text, (word, text)


def test_cheap_on_watchlist_in_english(english):
    resp = _ask(_db(), "what's cheap on my watchlist?")
    assert (resp.llm_trace or {}).get("intent") == "barato"
    lines = resp.answer.splitlines()
    assert lines[0] == "Saved readings, not live quotes or buy orders."
    assert "- Monthly contribution 300.00 EUR; horizon 10 years; since 2026-01-01." in lines
    assert "- 1 open alert; 0 active alert rules." in lines
    assert "No fair value (neither a published thesis nor the engine), so I can't say whether they're cheap: MSFT." in lines
    _no_spanish(resp.answer)


def test_risk_with_empty_portfolio_in_english(english):
    resp = _ask(_db(), "what's the risk in my portfolio?")
    assert (resp.llm_trace or {}).get("intent") == "riesgo"
    assert resp.answer.startswith("You have no saved positions in your portfolio, so there's no portfolio risk")
    assert "Alerts: 1 open alert; 0 active alert rules." in resp.answer
    assert "- KO: KO drops 5% (severity warning, 2026-10-31)." in resp.answer
    _no_spanish(resp.answer)


def test_risk_fallback_with_positions_in_english(english):
    resp = _fallback(_db(with_positions=True), "what's the risk in my portfolio?", "riesgo")
    assert "Concentration (portfolio): KO weighs 100.0% and the top 3 add up to 100.0%." in resp.answer
    assert "Weight by sector: Consumer 100.0%." in resp.answer
    assert "With unrealized losses: KO -15.4%." in resp.answer
    _no_spanish(resp.answer)


def test_model_context_stays_spanish(english):
    db = _db()
    db.info["language"] = "en"
    ctx = build_user_context(db, sections=("plan", "avisos"), dca_reader=lambda *_a: {})
    assert ctx is not None
    rendered = ctx.render()
    assert "Aportación mensual 300,00 EUR" in rendered and "1 avisos abiertos" in rendered
    assert "Monthly contribution" not in rendered and "open alert" not in rendered


def test_user_b_never_sees_user_a(english):
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "what's cheap on my watchlist?")
    assert "777.00 EUR" in resp.answer and "NVDA" in resp.answer and "TSLA drops 5%" in resp.answer
    for leak in ("300.00", "MSFT", "KO"):
        assert leak not in resp.answer


def test_spanish_unchanged():
    db = _db()
    resp = asyncio.run(ChatService(provider=_NoLLM()).answer(db, "¿qué está barato de mi watchlist?", "global", None))
    lines = resp.answer.splitlines()
    assert lines[0] == "Lecturas guardadas, no cotizaciones en directo ni órdenes de compra."
    assert "- Aportación mensual 300,00 EUR; horizonte 10 años; desde 2026-01-01." in lines
    assert "- 1 avisos abiertos; 0 reglas de aviso activas." in lines
