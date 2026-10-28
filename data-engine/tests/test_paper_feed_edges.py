"""Bordes del lote de propuestas LLM: reloj por defecto, conflicto de clave y lote vacio."""
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
from app.services.llm_proposal_runner import DAILY_QUOTA
from app.services.llm_proposal_service import ProposalRejected
from app.services.paper_feed_service import run_feed

NOW = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="feed-edge"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def company(db, ticker):
    row = Company(ticker=ticker, name=ticker, exchange="NASDAQ", company_type="large_cap", valuation_model="dcf")
    db.add(row)
    db.flush()
    return row


def news(db, co, score=8):
    db.add(NewsEvent(company_id=co.id, title=f"{co.ticker} t", date=NOW - timedelta(days=1), materiality_score=score))



def llm_trade(db, ticker):
    row = PaperTrade(
        proposal_key=f"llm:{ticker}:{NOW:%Y%m%d}:g", ticker=ticker, direction="long", horizon="short",
        thesis="t", conviction=Decimal("0.6"), proposed_entry=Decimal(100), stop=Decimal(80), target=Decimal(120),
        quantity=Decimal(1), author="LLM", inference_basis="b", status="pending",
    )
    db.add(row)
    db.flush()
    return row


def test_default_clock_is_used_when_none_injected(db):
    # Sin clock inyectado el lote usa el reloj real (_now): cuota completa y sin candidatos.
    out = asyncio.run(run_feed(db, generate=None, pause=0))
    assert out["status"] == "sin_candidatos"
    assert out["cuota_diaria"] == DAILY_QUOTA
    assert out["cuota_restante_al_inicio"] == DAILY_QUOTA


def test_key_conflict_is_isolated_and_does_not_stop_batch(db):
    for t in ("AAA", "BBB"):
        news(db, company(db, t))
    db.commit()

    async def generate(session, ticker, *, clock):
        if ticker == "AAA":
            raise ValueError("La clave ya pertenece a otra propuesta")
        return llm_trade(session, ticker)

    out = asyncio.run(run_feed(db, clock=lambda: NOW, generate=generate, pause=0))
    assert out["status"] == "ok"
    assert [g["ticker"] for g in out["guardadas"]] == ["BBB"]
    assert out["omitidas"] == [{"ticker": "AAA", "motivo": "conflicto_clave"}]


def test_batch_with_all_rejected_and_nothing_saved_is_sin_propuestas(db):
    for t in ("AAA", "BBB"):
        news(db, company(db, t))
    db.commit()

    async def generate(session, ticker, *, clock):
        raise ProposalRejected("sin_cotizacion")

    out = asyncio.run(run_feed(db, clock=lambda: NOW, generate=generate, pause=0))
    assert out["status"] == "sin_propuestas"
    assert out["guardadas"] == []
    assert {o["motivo"] for o in out["omitidas"]} == {"sin_cotizacion"}
