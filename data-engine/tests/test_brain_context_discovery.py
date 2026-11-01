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
            "formula_version": "nico-v2",
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


def test_radar_stale_scan_is_not_announced_as_current_signal(db):
    """4X confirmado y verificado escaneado hace 5 dias: NO es señal de hoy."""
    from datetime import timedelta

    comp = _company(db, "STAL")
    from app.services.propicks_radar_store import save_snapshot

    five_days_ago = datetime.now(UTC) - timedelta(days=5)
    save_snapshot(
        db,
        comp.id,
        {
            "status": "ok",
            "formula_version": "nico-v2",
            "price_verified": True,
            "price_date": five_days_ago.date().isoformat(),
            "source": "test",
            "current": {"level": 4},
            "confirmed": [{"level": 4}],
            "clear_price_signal": True,
            "daily_close_drawdown": 0.35,
            "drawdown_basis": "close",
        },
        now=five_days_ago,
    )
    db.commit()
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Qué dice el radar?")
    assert resp is not None
    assert "STAL" not in resp.answer
    assert "valores con señal clara" not in resp.answer
    assert "escaneo de más de 3 días" in resp.answer


def test_propicks_running_run_does_not_claim_none_passed(db):
    """Un run en curso no tiene ganadores todavia: no se dice 'ninguno paso'."""
    aapl = _company(db, "AAPL")
    _propick_run(db, [(aapl, 87.5)])
    running = ProPickRun(
        tenant_id=1,
        as_of=datetime(2026, 10, 31, 22, 0, tzinfo=UTC),
        status="running",
        funnel_version="nico-v1",
        universe_size=0,
        passed_count=0,
        top_n=20,
        duration_ms=0,
        params={},
    )
    db.add(running)
    db.commit()
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Qué ProPicks tengo?")
    assert resp is not None
    # Muestra el ultimo COMPLETADO y avisa del run en curso.
    assert "AAPL: score 87,5" in resp.answer
    assert "running" in resp.answer


def test_propicks_only_running_run_says_no_completed_run(db):
    _company(db, "AAPL")
    db.add(
        ProPickRun(
            tenant_id=1,
            as_of=datetime(2026, 10, 31, 22, 0, tzinfo=UTC),
            status="running",
            funnel_version="nico-v1",
            universe_size=0,
            passed_count=0,
            top_n=20,
            duration_ms=0,
            params={},
        )
    )
    db.commit()
    from app.services.brain_data_tools import answer_data_question

    resp = answer_data_question(db, "¿Qué ProPicks tengo?")
    assert resp is not None
    assert "ningún run de ProPicks completado" in resp.answer
    assert "running" in resp.answer
    assert "ninguno pasó" not in resp.answer
