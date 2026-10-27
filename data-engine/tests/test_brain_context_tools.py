"""Cerebro lee avisos, riesgo de cartera (panel + histórico) y diario de decisiones."""
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    AlertRule,
    Base,
    Company,
    DecisionJournalEntry,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    ResearchAlert,
)
from app.services.brain_context_tools import alerts_answer, portfolio_risk_answer
from app.services.brain_data_tools import answer_data_question
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker):
    comp = Company(ticker=ticker, name=f"{ticker} Holdings", exchange="NYSE", currency="USD",
                   company_type="operating", valuation_model="unassigned")
    db.add(comp)
    db.flush()
    return comp


def _alert(db, comp, title, *, tenant=1, status="open", severity="high", snoozed_until=None, days_ago=0):
    db.add(ResearchAlert(
        tenant_id=tenant, company_id=comp.id, severity=severity, status=status, alert_type="price_below",
        title=title, message=title, fingerprint=f"{title}-{tenant}", snoozed_until=snoozed_until,
        last_triggered_at=datetime.now(UTC) - timedelta(days=days_ago),
    ))


def test_alerts_question_lists_open_alerts_and_rules_without_llm(db):
    aapl, uber = _company(db, "AAPL"), _company(db, "UBER")
    _alert(db, aapl, "AAPL cae por debajo de 200", days_ago=1)
    _alert(db, uber, "UBER: noticia de la tesis", severity="medium", days_ago=0)
    _alert(db, uber, "Resuelto antiguo", status="resolved")
    _alert(db, uber, "Pospuesto", snoozed_until=datetime.now(UTC) + timedelta(days=2))
    _alert(db, aapl, "De otro tenant", tenant=2)
    db.add(AlertRule(tenant_id=1, company_id=aapl.id, name="AAPL < 200", rule_type="price_below",
                     condition={"threshold": 200}, active=True,
                     last_triggered_at=datetime.now(UTC) - timedelta(days=1)))
    db.add(AlertRule(tenant_id=1, company_id=uber.id, name="Inactiva", rule_type="news", active=False))
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1

    resp = asyncio.run(ChatService().answer(db, "¿Qué avisos tengo abiertos?", "portfolio", None))
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.llm_trace["path"] == "alerts"
    assert "Avisos abiertos: 2" in resp.answer
    # Más reciente primero, con gravedad en español.
    assert resp.answer.index("UBER: noticia") < resp.answer.index("AAPL cae")
    assert "gravedad alta" in resp.answer and "gravedad media" in resp.answer
    assert "Resuelto antiguo" not in resp.answer
    assert "De otro tenant" not in resp.answer
    assert "Pospuestos ahora mismo: 1" in resp.answer
    assert "Reglas de aviso activas: 1 (price_below 1)" in resp.answer
    assert "«AAPL < 200»" in resp.answer
    assert all(source["url"] == "/alerts" for source in resp.sources)


def test_alerts_for_a_named_company_are_scoped(db):
    aapl, uber = _company(db, "AAPL"), _company(db, "UBER")
    _alert(db, aapl, "AAPL cae")
    _alert(db, uber, "UBER sube")
    db.commit()
    resp = answer_data_question(db, "¿Hay alertas de UBER?")
    assert resp is not None
    assert "Avisos abiertos de UBER: 1" in resp.answer
    assert "AAPL cae" not in resp.answer


def test_creating_an_alert_is_not_answered_as_a_listing(db):
    _company(db, "AAPL")
    db.commit()
    resp = answer_data_question(db, "Crea un aviso si AAPL baja de 150")
    assert resp is None or resp.llm_trace.get("path") != "alerts"


def test_no_alerts_says_so(db):
    out = alerts_answer(db, 1)
    assert "No hay avisos abiertos." in out.answer
    assert "No hay reglas de aviso activas." in out.answer


def _snapshots(db, returns, *, tenant=1, start=None):
    portfolio = Portfolio(tenant_id=tenant, name=f"Main{tenant}")
    db.add(portfolio)
    db.flush()
    start = start or date.today() - timedelta(days=len(returns))
    for i, ret in enumerate(returns):
        db.add(PortfolioDailySnapshot(
            tenant_id=tenant, portfolio_id=portfolio.id, snapshot_date=start + timedelta(days=i + 1),
            base_currency="EUR", positions_value_base=Decimal("1000"), cash_value_base=Decimal("0"),
            total_value_base=Decimal("1000"), daily_return=None if ret is None else Decimal(str(ret)),
            pricing_coverage=Decimal("1"),
        ))


def test_drawdown_question_uses_snapshots_hand_checked(db):
    # Índice: 1,10 → 0,88 → 0,924. TWR = -7,6 %; pico 1,10, mínimo 0,88: caída máxima -20 %.
    db.info.pop("tenant_id", None)
    _snapshots(db, [None, 0.10, -0.20, 0.05])
    _snapshots(db, [0.5, 0.5], tenant=2)
    db.commit()
    db.info["tenant_id"] = 1
    resp = asyncio.run(ChatService().answer(db, "¿Cuál ha sido la caída máxima de mi cartera?", "portfolio", None))
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.llm_trace["path"] == "portfolio_risk"
    assert "rentabilidad TWR -7,6 %" in resp.answer
    assert "caída máxima -20,0 %" in resp.answer
    assert "3 cierres" in resp.answer
    # Menos de 20 rentabilidades: no se inventa una volatilidad anualizada.
    assert "volatilidad" not in resp.answer
    assert "no son una recomendación" in resp.answer


def test_volatility_is_annualised_with_the_series_own_frequency(db):
    # 30 snapshots diarios (calendario) alternando +1 % / -1 %: desviación muestral
    # ≈ 0,01017; frecuencia real ≈ 30/29·365,25 ≈ 377,8 → ≈ 19,8 % anual.
    _snapshots(db, [0.01 if i % 2 == 0 else -0.01 for i in range(30)])
    db.commit()
    out = portfolio_risk_answer(db, 1)
    assert "volatilidad anualizada 19,8 %" in out.answer


def test_risk_dashboard_rules_reach_the_risk_answer(db):
    big, small = _company(db, "BIG"), _company(db, "SMALL")
    db.add(Position(tenant_id=1, company_id=big.id, quantity=Decimal("1"), average_cost=Decimal("1"),
                    currency="EUR", base_currency="EUR", market_value=Decimal("800")))
    db.add(Position(tenant_id=1, company_id=small.id, quantity=Decimal("1"), average_cost=Decimal("1"),
                    currency="EUR", base_currency="EUR", market_value=Decimal("200")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué riesgos tiene mi cartera?", "portfolio", None))
    # La respuesta de concentración de siempre sigue ahí...
    assert resp.prompt_version == "portfolio-analysis-v1"
    assert "Mayor posición: BIG" in resp.answer
    # ...y ahora suma las reglas del panel de riesgo.
    assert "BIG supera el 20 % de peso en la cartera" in resp.answer
    assert any(source.get("url") == "/risk" for source in resp.sources)


def test_journal_lists_open_decisions_first_with_link(db):
    aapl, uber = _company(db, "AAPL"), _company(db, "UBER")
    db.add(DecisionJournalEntry(tenant_id=1, company_id=aapl.id, decision_date=date(2026, 9, 1), decision="buy",
                                rationale="Recompras y servicios", what_must_be_true=["margen > 45 %", ""],
                                price=Decimal("210.5"), status="open"))
    db.add(DecisionJournalEntry(tenant_id=1, company_id=uber.id, decision_date=date(2026, 10, 1), decision="trim",
                                rationale="Peso excesivo", status="closed"))
    db.add(DecisionJournalEntry(tenant_id=2, company_id=uber.id, decision_date=date(2026, 10, 2), decision="sell",
                                rationale="SECRETO", status="open"))
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    resp = asyncio.run(ChatService().answer(db, "¿Qué hay en mi diario de decisiones?", "portfolio", None))
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.llm_trace["path"] == "decision_journal"
    assert "1 abiertas de las últimas 2" in resp.answer
    assert resp.answer.index("AAPL") < resp.answer.index("UBER")
    assert "comprar a 210,50 (abierta)" in resp.answer
    assert "Debe cumplirse: 1 condición(es)" in resp.answer
    assert "recortar" in resp.answer
    assert "SECRETO" not in resp.answer
    assert resp.sources[0]["url"] == "/research/AAPL/decision-lessons"


def test_journal_scoped_to_named_company_and_empty_case(db):
    aapl = _company(db, "AAPL")
    _company(db, "UBER")
    db.add(DecisionJournalEntry(tenant_id=1, company_id=aapl.id, decision_date=date(2026, 9, 1),
                                decision="hold", rationale="r", status="open"))
    db.commit()
    resp = answer_data_question(db, "¿Qué decisiones tomé con UBER en el diario?")
    assert resp is not None
    assert "No hay entradas en tu diario de decisiones de UBER." in resp.answer
