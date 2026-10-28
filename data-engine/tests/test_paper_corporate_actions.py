"""Dividendos y splits del paper book: fuente etiquetada, cierres intocables."""
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
    PENDING_SPLIT_WARNING,
    accrued_dividends,
    sync_corporate_actions,
    sync_dividends,
)
from app.services.paper_cost_service import PaperCostAssumptions, pnl_net
from app.services.paper_trading_service import apply_quote, pnl, refresh_trades, scoreboard, trade_out

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
COSTS = PaperCostAssumptions(commission_flat=Decimal("1.00"), spread_bps=Decimal("5"), version="supuesto-v1|fija=1.00|spread_bps=5")


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


def company(db, ticker="ASTS"):
    row = Company(ticker=ticker, name=ticker, exchange="NASDAQ", company_type="large_cap", valuation_model="dcf")
    db.add(row)
    db.flush()
    return row


def dividend(db, co, ex, amount, currency="USD", source="yahoo_finance"):
    row = DividendRecord(company_id=co.id, ex_date=ex, amount=Decimal(str(amount)), currency=currency, source=source)
    row.tenant_id = 1
    db.add(row)
    db.flush()
    return row


def split(db, co, effective, ratio, source="yahoo_finance"):
    row = CorporateAction(company_id=co.id, action_type="split", effective_date=effective, ratio=Decimal(str(ratio)), source=source)
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


def test_long_accrues_dividend_in_window(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    dividend(db, co, NOW.date() + timedelta(days=1), "0.5")
    accrual = accrued_dividends(db, row, until=NOW.date() + timedelta(days=2))
    assert accrual.total == Decimal("1.0")  # 0,5 x 2 acciones
    assert accrual.count == 1
    # Fuera de ventana no cuenta
    dividend(db, co, NOW.date() - timedelta(days=3), "9.99")  # anterior a la entrada
    assert accrued_dividends(db, row, until=NOW.date() + timedelta(days=2)).count == 1


def test_short_pays_dividend(db):
    co = company(db)
    row = trade(direction="short", stop=110, target=80)
    db.add(row)
    apply_quote(row, quote(102), NOW, costs=COSTS)
    dividend(db, co, NOW.date() + timedelta(days=1), "0.5")
    accrual = accrued_dividends(db, row, until=NOW.date() + timedelta(days=2))
    assert accrual.total == Decimal("-1.0")


def test_wrong_currency_skipped_and_counted(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    dividend(db, co, NOW.date() + timedelta(days=1), "0.5", currency="EUR")
    accrual = accrued_dividends(db, row, until=NOW.date() + timedelta(days=2))
    assert accrual.total == 0 and accrual.count == 0 and accrual.wrong_currency == 1


def test_uncertain_yahoo_group_excluded(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    ex = NOW.date() + timedelta(days=1)
    dividend(db, co, ex, "0.5")
    dividend(db, co, ex, "0.25")  # mismo dia ex, importe distinto: INCIERTO
    accrual = accrued_dividends(db, row, until=NOW.date() + timedelta(days=2))
    assert accrual.count == 0 and accrual.uncertain == 1 and accrual.total == 0


def test_split_adjusts_open_trade_idempotent(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    split(db, co, NOW.date() + timedelta(days=1), "4")
    assert sync_corporate_actions(db, row)
    assert row.quantity == Decimal(8)
    assert row.entry_price == Decimal("25.000000")
    assert row.stop == Decimal("22.500000")
    assert row.target == Decimal("30.000000")
    assert row.proposed_entry == Decimal("100.000000")  # propuesta: inmutable
    assert row.split_adjustments == 1
    assert "yahoo_finance" in row.last_corporate_action
    assert not sync_corporate_actions(db, row)  # idempotente
    assert row.quantity == Decimal(8)


def test_split_blocks_pending_fills(db):
    co = company(db)
    row = trade()
    db.add(row)
    db.flush()
    split(db, co, NOW.date() - timedelta(hours=12), "4")  # tras la propuesta, antes del fill
    result = refresh_trades(db, fetch_quote=lambda ticker: quote(99))
    row2 = db.get(PaperTrade, row.id)
    assert row2.corporate_action_warning == PENDING_SPLIT_WARNING
    assert row2.status == "pending"  # sin fill: niveles pre-split no son comparables
    assert row2.entry_price is None


def test_split_on_closed_flags_without_rewrite_and_excludes_hitrate(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    later = NOW + timedelta(days=2)
    apply_quote(row, quote(120, later), later, costs=COSTS)  # cierra por objetivo
    assert row.status == "closed"
    split(db, co, NOW.date() + timedelta(days=1), "4")  # dentro de (entrada, salida]
    assert sync_corporate_actions(db, row)
    assert row.corporate_action_warning == CLOSED_SPLIT_WARNING
    assert row.exit_price == Decimal("120")  # cierre intacto
    board = scoreboard([row], later)
    group = board["groups"][0]
    assert group["closed"] == 0  # excluida de las estadisticas
    assert group["closed_distorted"] == 1
    assert group["hit_rate"] is None


def test_closed_net_includes_dividends(db):
    co = company(db)
    row = trade()
    db.add(row)
    apply_quote(row, quote(100), NOW, costs=COSTS)
    dividend(db, co, NOW.date() + timedelta(days=1), "0.5")
    later = NOW + timedelta(days=3)
    apply_quote(row, quote(85, later), later, costs=COSTS)  # stop
    assert sync_dividends(db, row)
    assert row.dividends_total == Decimal("1.0")
    net = pnl_net(row, row.exit_price)
    gross = pnl(row, row.exit_price)
    assert net == gross - row.entry_fee - row.exit_fee + Decimal("1.0")
    out = trade_out(row, later)
    assert out["realized_pnl_net"] == net
    assert out["dividends_total"] == Decimal("1.0")
    assert out["dividends_count"] == 1
    assert out["dividends_source"] is not None
