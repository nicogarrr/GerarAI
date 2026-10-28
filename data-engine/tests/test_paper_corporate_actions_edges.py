"""Bordes de dividendos y splits: ventanas exactas, ratios invalidos y no-computable = None."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Tenant
from app.models.entities import Company, CorporateAction, DividendRecord
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_corporate_actions_service import (
    CLOSED_SPLIT_WARNING,
    accrued_dividends,
    sync_corporate_actions,
    sync_dividends,
)
from app.services.paper_cost_service import PaperCostAssumptions
from app.services.paper_trading_service import apply_quote

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
COSTS = PaperCostAssumptions(commission_flat=Decimal("1.00"), spread_bps=Decimal("5"), version="supuesto-v1|fija=1.00|spread_bps=5")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="corp-edge"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def company(db, ticker="ASTS"):
    row = Company(ticker=ticker, name=ticker, exchange="NASDAQ", company_type="large_cap", valuation_model="dcf")
    db.add(row)
    db.flush()
    return row


def dividend(db, co, ex, amount, currency="USD"):
    row = DividendRecord(company_id=co.id, ex_date=ex, amount=Decimal(str(amount)), currency=currency, source="yahoo_finance")
    row.tenant_id = 1
    db.add(row)
    db.flush()
    return row


def split(db, co, effective, ratio):
    row = CorporateAction(company_id=co.id, action_type="split", effective_date=effective, ratio=Decimal(str(ratio)), source="yahoo_finance")
    row.tenant_id = 1
    db.add(row)
    db.flush()
    return row


def body(**kwargs):
    return {"proposal_key": "run-1-ASTS", "ticker": "ASTS", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "90", "target": "120", "quantity": "2",
            "inference_basis": "Inferido a partir de los documentos oficiales", **kwargs}


def trade(**kwargs):
    return PaperTrade(**PaperProposal(**body(**kwargs)).model_dump(), author="LLM",
                      inference_label="inferencia", status="pending", created_at=NOW - timedelta(days=1))


def quote(price=100, at=NOW, currency="USD"):
    return {"live_c": price, "live_t": at.timestamp(), "currency": currency}


def test_accrual_not_computable_returns_none(db):
    pending = trade()
    db.add(pending)
    assert accrued_dividends(db, pending, until=NOW.date()) is None  # sin entrada: N/D
    no_currency = trade()
    no_currency.status, no_currency.entry_at, no_currency.currency = "open", NOW, None
    db.add(no_currency)
    assert accrued_dividends(db, no_currency, until=NOW.date()) is None  # sin divisa: N/D


def test_window_bounds_ex_day_strictly_after_entry_until_inclusive(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)  # entrada el dia D
    dividend(db, co, NOW.date(), "9.99")  # ex = dia de entrada: FUERA (ventana abierta)
    dividend(db, co, NOW.date() + timedelta(days=2), "0.5")  # ex = hasta: DENTRO (cerrada)
    accrual = accrued_dividends(db, row, until=NOW.date() + timedelta(days=2))
    assert accrual.count == 1
    assert accrual.total == Decimal("1.0")  # solo el del limite, 0,5 x 2 acciones


def test_sync_dividends_without_events_keeps_source_empty_and_is_idempotent(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    assert sync_dividends(db, row)  # primera vez: NULL -> 0 computado
    assert row.dividends_total == 0 and row.dividends_count == 0
    assert row.dividends_source is None  # sin eventos no hay fuente que etiquetar
    assert not sync_dividends(db, row)  # recomputo idempotente: sin cambios


def test_sync_corporate_actions_without_actions_is_noop(db):
    company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    assert not sync_corporate_actions(db, row)
    assert row.split_adjustments is None
    assert row.last_corporate_action is None


def test_invalid_split_ratio_is_skipped_valid_one_applies(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    bad = split(db, co, NOW.date() + timedelta(days=1), "0")  # ratio invalido: se ignora
    good = split(db, co, NOW.date() + timedelta(days=2), "2")
    assert sync_corporate_actions(db, row)
    assert row.quantity == Decimal("4.000000")  # solo el split valido
    assert row.entry_price == Decimal("50.000000")
    assert str(good.id) in row.applied_split_ids
    assert str(bad.id) not in row.applied_split_ids
    assert row.split_adjustments == 1


def test_closed_trade_already_warned_is_not_processed_twice(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    later = NOW + timedelta(days=2)
    apply_quote(row, quote(120, later), later, costs=COSTS)  # cierra por objetivo
    assert row.status == "closed"
    row.corporate_action_warning = CLOSED_SPLIT_WARNING  # ya etiquetada en un sync anterior
    split(db, co, NOW.date() + timedelta(days=1), "4")
    assert not sync_corporate_actions(db, row)  # no duplica aviso ni toca el cierre
    assert row.corporate_action_warning == CLOSED_SPLIT_WARNING
    assert row.exit_price == Decimal("120")

