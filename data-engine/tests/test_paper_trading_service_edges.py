"""Bordes del servicio paper: carrera de clave, N/D legados, supuesto vigente y refresh."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.services.paper_trading_service as service
from app.core.database import Base
from app.models import Tenant
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_cost_service import (
    PaperCostAssumptions,
    current_assumptions,
    execution_fee,
)
from app.services.paper_trading_service import (
    apply_quote,
    create_proposal,
    deadline,
    pnl,
    refresh_trades,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
COSTS = PaperCostAssumptions(commission_flat=Decimal("1.00"), spread_bps=Decimal("5"), version="supuesto-v1|fija=1.00|spread_bps=5")


def body(**kwargs):
    return {"proposal_key": "run-1-ASTS", "ticker": "ASTS", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "90", "target": "120", "quantity": "2",
            "inference_basis": "Inferido a partir de los documentos oficiales", **kwargs}


def trade(**kwargs):
    return PaperTrade(**PaperProposal(**body(**kwargs)).model_dump(), author="LLM",
                      inference_label="inferencia", status="pending", created_at=NOW - timedelta(seconds=1))


def quote(price=100, at=NOW, currency="USD"):
    return {"live_c": price, "live_t": at.timestamp(), "currency": currency}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="svc-edge"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_concurrent_identical_retry_returns_the_race_winner(db):
    proposal = PaperProposal(**body(proposal_key="race-1"))
    real_commit = db.commit
    fired = {"done": False}
    winner_id = {}

    def raced_commit():
        if fired["done"]:
            return real_commit()
        fired["done"] = True
        db.rollback()  # nuestro insert pierde la carrera
        winner = PaperTrade(
            **{**proposal.model_dump(), "ticker": proposal.ticker.upper()},
            proposal_currency=proposal.currency, proposal_currency_known=True,
        )
        db.add(winner)
        real_commit()
        winner_id["id"] = winner.id
        raise IntegrityError("INSERT INTO paper_trades ...", {}, Exception("UNIQUE constraint failed"))

    db.commit = raced_commit
    row = create_proposal(db, proposal)
    assert row.id == winner_id["id"]  # mismo envio: se devuelve el ganador, no un 409


def test_integrity_error_without_visible_winner_is_reraised(db):
    def ghost_commit():
        db.rollback()
        raise IntegrityError("INSERT INTO paper_trades ...", {}, Exception("UNIQUE constraint failed"))

    db.commit = ghost_commit
    with pytest.raises(IntegrityError):
        create_proposal(db, PaperProposal(**body(proposal_key="ghost-1")))


def test_pnl_and_deadline_are_none_without_entry():
    row = trade()
    assert row.entry_price is None and row.entry_at is None
    assert pnl(row, Decimal(100)) is None
    assert pnl(row, None) is None
    assert deadline(row) is None


def test_exit_fee_uses_current_assumptions_when_costs_not_passed():
    # Trade con costes de entrada persistidos: la salida estima con el supuesto VIGENTE.
    row = trade()
    apply_quote(row, quote(98), NOW, costs=COSTS)
    assert row.entry_fee == execution_fee(Decimal(98), row.quantity, COSTS)
    later = NOW + timedelta(hours=1)
    assert apply_quote(row, quote(85, later), later)  # sin costs=
    assert row.close_reason == "stop"
    current = current_assumptions()
    assert row.exit_fee == execution_fee(Decimal(85), row.quantity, current)
    assert row.cost_assumption_version == COSTS.version  # la version de entrada no se reescribe


def test_refresh_only_id_limits_discovery_to_that_trade(db):
    one = create_proposal(db, PaperProposal(**body(proposal_key="only-1", ticker="AAA")))
    create_proposal(db, PaperProposal(**body(proposal_key="only-2", ticker="BBB")))
    fetched = []
    result = refresh_trades(db, lambda ticker: fetched.append(ticker) or {}, only_id=one.id)
    assert fetched == ["AAA"]
    assert result["symbols_checked"] == 1


def test_refresh_caps_provider_calls_at_50_symbols(db):
    for i in range(51):
        create_proposal(db, PaperProposal(**body(proposal_key=f"cap-{i:02d}", ticker=f"C{i:02d}")))
    fetched = []
    result = refresh_trades(db, lambda ticker: fetched.append(ticker) or {})
    assert result["symbols_checked"] == 50
    assert len(fetched) == 50
    assert "C50" not in fetched  # el resto no gasta llamadas al proveedor
    assert result["updated"] == 0  # sin cotizacion no se inventa marca


def test_provider_exception_never_fabricates_a_mark(db):
    create_proposal(db, PaperProposal(**body(proposal_key="boom-1")))

    def boom(ticker):
        raise RuntimeError("proveedor caido")

    result = refresh_trades(db, boom)
    assert result == {"updated": 0, "unchanged": 1, "symbols_checked": 1}
    row = db.scalar(select(PaperTrade))
    assert row.status == "pending" and row.mark_price is None


def test_refresh_fills_pending_at_observed_price_with_current_costs(db):
    row = create_proposal(db, PaperProposal(**body(proposal_key="fill-1")))
    row.created_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    fresh = datetime.now(UTC)
    result = refresh_trades(db, lambda ticker: quote(98, fresh))
    assert result["updated"] == 1
    db.expire_all()
    stored = db.get(PaperTrade, row.id)
    assert stored.status == "open"
    assert stored.entry_price == Decimal(98)  # fill al spot observado, no al limite propuesto (100)
    assert stored.entry_fee == execution_fee(Decimal(98), stored.quantity, current_assumptions())
    assert stored.price_source == "yahoo_finance_spot"


def test_row_processing_error_rolls_back_and_propagates(db, monkeypatch):
    create_proposal(db, PaperProposal(**body(proposal_key="err-1")))

    def broken(row, quote, now, *, costs=None):
        raise RuntimeError("estado corrupto")

    monkeypatch.setattr(service, "apply_quote", broken)
    with pytest.raises(RuntimeError, match="estado corrupto"):
        refresh_trades(db, lambda ticker: quote(98, datetime.now(UTC)))
    assert db.scalar(select(PaperTrade)).status == "pending"  # rollback limpio
