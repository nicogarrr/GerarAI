import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Tenant
from app.models.entities import Company, NewsEvent
from app.models.paper_trading import PaperTrade
from app.services.llm_proposal_runner import DAILY_QUOTA, QuotaExceeded
from app.services.llm_proposal_service import ProposalRejected
from app.services.paper_feed_service import MIN_MATERIALITY, run_feed, select_candidates

NOW = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def company(db, ticker):
    row = Company(ticker=ticker, name=ticker, exchange="NASDAQ", company_type="large_cap", valuation_model="dcf")
    db.add(row)
    db.flush()
    return row


def news(db, co, score, days=1):
    db.add(NewsEvent(company_id=co.id, title=f"{co.ticker} t", date=NOW - timedelta(days=days), materiality_score=score))


def llm_trade(db, ticker, *, status="pending", created=NOW, key=None):
    row = PaperTrade(
        proposal_key=key or f"llm:{ticker}:{created:%Y%m%d}:x", ticker=ticker, direction="long", horizon="short",
        thesis="t", conviction=Decimal("0.6"), proposed_entry=Decimal(100), stop=Decimal(80), target=Decimal(120),
        quantity=Decimal(1), author="LLM", inference_basis="b", status=status,
    )
    db.add(row)
    db.flush()
    row.created_at = created
    return row


def test_candidates_ranked_by_materiality_and_filtered(db):
    a, b, c, d = (company(db, t) for t in ("AAA", "BBB", "CCC", "DDD"))
    news(db, a, MIN_MATERIALITY)
    news(db, b, 9)
    news(db, c, MIN_MATERIALITY - 1)  # poco material
    news(db, d, 9, days=30)  # fuera de ventana
    db.commit()
    assert select_candidates(db, NOW, 10) == ["BBB", "AAA"]


def test_candidates_exclude_live_or_today_llm_proposals(db):
    a, b, c = (company(db, t) for t in ("AAA", "BBB", "CCC"))
    for co in (a, b, c):
        news(db, co, 8)
    llm_trade(db, "AAA", status="open", created=NOW - timedelta(days=9))
    llm_trade(db, "BBB", status="closed", created=NOW)
    llm_trade(db, "CCC", status="closed", created=NOW - timedelta(days=3))
    db.commit()
    assert select_candidates(db, NOW, 10) == ["CCC"]


def _feed(db, generate, **kwargs):
    return asyncio.run(run_feed(db, clock=lambda: NOW, generate=generate, pause=0, **kwargs))


def test_feed_saves_up_to_remaining_quota_and_never_more(db):
    for i in range(10):
        news(db, company(db, f"T{i:02d}"), 8)
    llm_trade(db, "OLD", status="closed", created=NOW - timedelta(hours=1))
    llm_trade(db, "OLD2", status="closed", created=NOW - timedelta(hours=1), key="llm:OLD2:20261009:y")
    db.commit()
    calls: list[str] = []

    async def generate(session, ticker, *, clock):  # noqa: ARG001
        calls.append(ticker)
        return llm_trade(session, ticker, key=f"llm:{ticker}:20261009:g")

    out = _feed(db, generate)
    assert len(out["guardadas"]) == DAILY_QUOTA - 2 == out["cuota_restante_al_inicio"]
    assert len(calls) == DAILY_QUOTA - 2


def test_feed_quota_exhausted_makes_no_calls(db):
    co = company(db, "AAA")
    news(db, co, 9)
    for i in range(DAILY_QUOTA):
        llm_trade(db, f"X{i}", status="closed", created=NOW - timedelta(minutes=i + 1), key=f"llm:X{i}:20261009:q")
    db.commit()

    async def generate(*args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("no debe llamar al LLM con la cuota agotada")

    out = _feed(db, generate)
    assert out["status"] == "cuota_agotada" and out["guardadas"] == []


def test_rejection_of_one_ticker_does_not_stop_batch_but_budget_does(db):
    for t in ("AAA", "BBB", "CCC"):
        news(db, company(db, t), 8)
    db.commit()

    async def generate(session, ticker, *, clock):  # noqa: ARG001
        if ticker == "AAA":
            raise ProposalRejected("sin_cotizacion")
        if ticker == "BBB":
            return llm_trade(session, ticker, key="llm:BBB:20261009:g")
        raise ProposalRejected("presupuesto_agotado")

    out = _feed(db, generate)
    assert [g["ticker"] for g in out["guardadas"]] == ["BBB"]
    assert {o["motivo"] for o in out["omitidas"]} == {"sin_cotizacion", "presupuesto_agotado"}
    assert out["status"] == "presupuesto_agotado"


def test_unexpected_error_in_one_ticker_is_isolated(db):
    for t in ("AAA", "BBB"):
        news(db, company(db, t), 8)
    db.commit()

    async def generate(session, ticker, *, clock):  # noqa: ARG001
        if ticker == "AAA":
            raise RuntimeError("boom")
        return llm_trade(session, ticker, key="llm:BBB:20261009:g")

    out = _feed(db, generate)
    assert [g["ticker"] for g in out["guardadas"]] == ["BBB"]
    assert out["omitidas"] == [{"ticker": "AAA", "motivo": "error_RuntimeError"}]


def test_quota_exceeded_during_batch_stops_cleanly(db):
    for t in ("AAA", "BBB"):
        news(db, company(db, t), 8)
    db.commit()

    async def generate(session, ticker, *, clock):  # noqa: ARG001
        raise QuotaExceeded(DAILY_QUOTA)

    out = _feed(db, generate)
    assert out["status"] == "cuota_agotada" and out["guardadas"] == []


def test_no_candidates_and_label(db):
    out = _feed(db, None)
    assert out["status"] == "sin_candidatos" and out["etiqueta"] == "INFERIDO"


def test_future_dated_news_is_never_a_candidate(db):
    co = company(db, "AAA")
    news(db, co, 9, days=-1)  # fecha de manana
    db.commit()
    assert select_candidates(db, NOW, 10) == []


def test_candidate_exclusion_uses_author_not_only_key(db):
    co = company(db, "AAA")
    news(db, co, 8)
    llm_trade(db, "AAA", status="open", created=NOW - timedelta(days=9), key="manual-otra-clave")
    db.commit()
    assert select_candidates(db, NOW, 10) == []


def test_each_call_gets_the_current_clock_not_a_frozen_one(db):
    for t in ("AAA", "BBB"):
        news(db, company(db, t), 8)
    db.commit()
    ticks = iter(NOW + timedelta(minutes=i) for i in range(100))
    seen: list[datetime] = []

    async def generate(session, ticker, *, clock):  # noqa: ARG001
        seen.append(clock())
        return llm_trade(session, ticker, key=f"llm:{ticker}:20261009:g")

    asyncio.run(run_feed(db, clock=lambda: next(ticks), generate=generate, pause=0))
    assert len(seen) == 2 and seen[0] < seen[1]  # el reloj avanza entre llamadas


def test_scheduler_registers_daily_proposals(monkeypatch):
    from app.workers import scheduler as sched

    seen = {}
    orig = sched._register

    def spy(scheduler, func, trigger, *, job_id, **kw):
        seen[job_id] = (trigger, dict(kw))

    monkeypatch.setattr(sched, "_register", spy)
    sched.build_scheduler(background=True)
    assert "paper_proposals_daily" in seen
    trigger, kwargs = seen["paper_proposals_daily"]
    assert trigger == "cron"
    assert kwargs.get("hour") == 15 and kwargs.get("minute") == 30
    assert "paper_dividends_daily" in seen


def test_ownership_disclosure_cannot_seed_automatic_paper_proposal(db):
    co = company(db, 'ASTS')
    db.add(NewsEvent(company_id=co.id, title='Declaración de participación: Vanguard',
                     date=NOW - timedelta(hours=1), materiality_score=6,
                     event_type='ownership_disclosure'))
    db.commit()
    assert select_candidates(db, NOW, 10) == []
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('disclosure must not invoke paper LLM')
    assert _feed(db, forbidden)['status'] == 'sin_candidatos'
    assert calls == []
    news(db, co, 7)
    db.commit()
    # A separate real material event may still qualify the same ticker.
    assert select_candidates(db, NOW, 10) == ['ASTS']
