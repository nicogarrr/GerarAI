"""Enrutado Cerebro: ProPicks, radar y salud de fuentes (pregunta -> respuesta).

Antes de este cableado el Cerebro no podia responder sobre el scorer
(ProPicks), el radar de precio ni la salud de las fuentes aunque los datos
estuvieran guardados. Las respuestas leen SOLO datos almacenados (ultimo run,
snapshots del radar, inventario de fuentes) y dicen su fecha; nunca inventan.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.models.entities import Base, ProPickCandidate, ProPickRun


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker):
    row = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="TEST", currency="USD",
        sector="Tech", industry="Software", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(row)
    db.flush()
    return row


def _propick_run(db, ranked):
    run = ProPickRun(
        tenant_id=1,
        as_of=datetime(2026, 10, 30, 22, 0, tzinfo=UTC),
        status="completed",
        funnel_version="nico-v1",
        universe_size=50,
        passed_count=len(ranked),
        top_n=20,
        duration_ms=100,
        params={},
    )
    db.add(run)
    db.flush()
    for rank, (comp, score) in enumerate(ranked, start=1):
        db.add(
            ProPickCandidate(
                tenant_id=1, run_id=run.id, company_id=comp.id, passed=True,
                rank=rank, score=score, failed_gates=[], metrics={}, coverage={},
            )
        )
    db.commit()
    return run


def test_propicks_question_returns_last_run_with_scores_and_date(db):
    aapl = _company(db, "AAPL")
    msft = _company(db, "MSFT")
    _propick_run(db, [(aapl, 87.5), (msft, 81.0)])
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Qué ProPicks tengo ahora mismo?")
    assert resp is not None
    assert resp.llm_trace.get("path") == "propicks"
    assert "AAPL: score 87,5" in resp.answer
    assert "MSFT" in resp.answer
    assert "2026" in resp.answer  # fecha del run publicada
    assert any(s.get("url") == "/propicks" for s in resp.sources)


def test_propicks_without_run_says_so_without_inventing(db):
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Qué ProPicks tengo?")
    assert resp is not None
    assert "no hay ningún run" in resp.answer.lower()
    assert resp.sources == []


def test_radar_question_lists_clear_signals_from_saved_snapshots(db):
    comp = _company(db, "XYZW")
    from app.services.propicks_radar_store import save_snapshot

    save_snapshot(
        db,
        comp.id,
        {
            "status": "ok",
            "formula_version": "nico-v1",
            "price_verified": True,
            "price_date": "2026-10-30",
            "source": "test",
            "current": {"level": 4},
            "confirmed": [{"level": 4}],
            "clear_price_signal": True,
            "daily_close_drawdown": 0.35,
            "drawdown_basis": "close",
        },
        now=datetime(2026, 10, 30, 15, 0, tzinfo=UTC),
    )
    db.commit()
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Qué dice el radar?")
    assert resp is not None
    assert resp.llm_trace.get("path") == "radar"
    assert "XYZW" in resp.answer
    assert "señal clara" in resp.answer
    assert "no una orden de compra" in resp.answer


def test_radar_without_snapshots_says_so(db):
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Qué dice el radar?")
    assert resp is not None
    assert "no tiene snapshots guardados" in resp.answer


def test_source_health_question_summarizes_layers(db):
    from app.services import data_health_service

    data_health_service._CACHE.clear()
    comp = _company(db, "AAPL")
    db.add(
        FinancialFact(
            company_id=comp.id, metric="revenue", value=Decimal("100"), unit="USD",
            period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
            source_type="sec_edgar", is_reported=True, confidence=Decimal("0.9"),
        )
    )
    db.add(
        MarketPrice(
            company_id=comp.id, date=date(2026, 10, 30), close=Decimal("10"),
            adj_close=Decimal("10"), source="yfinance",
        )
    )
    db.commit()
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Cómo van las fuentes de datos?")
    assert resp is not None
    assert resp.llm_trace.get("path") == "source_health"
    assert "Fundamentales" in resp.answer
    assert "Precios diarios" in resp.answer
    assert "última escritura" in resp.answer


def test_unrelated_question_is_not_routed_to_discovery(db):
    from app.services.brain_data_tools import answer_data_question

    assert answer_data_question(db, "¿qué tiempo hace en Madrid?") is None
