"""Supervivientes de mutacion en ``paper_trading_service`` (ronda 3).

El scoreboard (por grupo y por bin de conviction) no tenia ningun test que
fijase sus cifras: un ``>=`` por ``>`` en las victorias, un ``-`` por ``+`` en
los planos o un bin desplazado pasaban. Tambien los bordes exactos de stop,
objetivo y entrada, la antiguedad maxima de la cotizacion, el horizonte de
5 anos y el refresco de posiciones abiertas.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Tenant
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_cost_service import PaperCostAssumptions
from app.services.paper_trading_service import (
    _same_proposal,
    apply_quote,
    deadline,
    refresh_trades,
    scoreboard,
    trade_out,
    utc,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
COSTS = PaperCostAssumptions(commission_flat=Decimal("1"), spread_bps=Decimal("0"), version="v")
_SEQ = iter(range(10_000))


def row(*, status="closed", direction="long", horizon="short", conviction="0.8", entry=100, exit_=None,
        mark=None, mark_at=None, currency="USD", entry_fee=None, exit_fee=None, warning=None,
        stop=None, target=None, proposed=100, ticker="ASTS"):
    long = direction == "long"
    trade = PaperTrade(
        proposal_key=f"k{next(_SEQ)}", ticker=ticker, direction=direction, horizon=horizon, thesis="t",
        conviction=Decimal(conviction), proposed_entry=Decimal(proposed),
        stop=Decimal(stop if stop is not None else (90 if long else 110)),
        target=Decimal(target if target is not None else (120 if long else 80)),
        quantity=Decimal(2), author="LLM", inference_basis="b", status=status,
        created_at=NOW - timedelta(days=3),
    )
    trade.entry_price = None if entry is None else Decimal(entry)
    trade.entry_at = None if entry is None else NOW - timedelta(days=2)
    trade.exit_price = None if exit_ is None else Decimal(exit_)
    trade.mark_price = None if mark is None else Decimal(mark)
    trade.mark_at = mark_at
    trade.currency, trade.entry_fee, trade.exit_fee = currency, entry_fee, exit_fee
    trade.corporate_action_warning = warning
    return trade


def test_scoreboard_exact_cells_and_bins():
    rows = [
        row(exit_=120, conviction="0.75", entry_fee=Decimal(1), exit_fee=Decimal(1)),  # +40 / neto +38
        row(exit_=90, conviction="0.5", entry_fee=Decimal(1), exit_fee=Decimal(1)),    # -20 / neto -22
        row(exit_=100, conviction="0.3"),                                               # plano, legado
        row(status="open", mark=110, mark_at=NOW - timedelta(hours=1)),                 # +20 abierto
        row(status="open", mark=130, mark_at=NOW - timedelta(hours=25)),                # sin marca fresca
        row(status="pending", entry=None),
        row(exit_=10, conviction="0.9", warning="split_cerrado_sin_ajustar"),
        row(status="pending", entry=None, horizon="five_years", currency=None),
    ]
    data = scoreboard(rows, NOW)
    assert data["groups"] == [
        {"horizon": "five_years", "currency": "sin_datos", "proposals": 1, "closed": 0, "open": 0,
         "wins": 0, "losses": 0, "flat": 0, "hit_rate": None, "realized_pnl": None,
         "closed_distorted": 0, "closed_net": 0, "hit_rate_net": None, "realized_pnl_net": None,
         "unrealized_pnl": None, "missing_marks": 0},
        {"horizon": "short", "currency": "USD", "proposals": 7, "closed": 3, "open": 2,
         "wins": 1, "losses": 1, "flat": 1, "hit_rate": 1 / 3, "realized_pnl": Decimal(20),
         "closed_distorted": 1, "closed_net": 2, "hit_rate_net": 0.5, "realized_pnl_net": Decimal(16),
         "unrealized_pnl": Decimal(20), "missing_marks": 1},
    ]
    assert data["conviction_bins"] == [
        {"conviction_min": 0, "conviction_max": 0.5, "closed": 1, "hit_rate": 0.0},
        {"conviction_min": 0.5, "conviction_max": 0.75, "closed": 1, "hit_rate": 0.0},
        {"conviction_min": 0.75, "conviction_max": 1, "closed": 1, "hit_rate": 1.0},
    ]
    assert data["hit_rate"] == "positive_gross_return_on_closed_positions"
    assert data["mode"] == "paper"


def test_scoreboard_short_results_use_the_short_sign():
    data = scoreboard([row(direction="short", exit_=90), row(direction="short", exit_=104)], NOW)
    (cell,) = data["groups"]
    assert (cell["wins"], cell["losses"], cell["realized_pnl"]) == (1, 1, Decimal(12))


@pytest.mark.parametrize(("age", "fresh"), [(timedelta(0), True), (timedelta(hours=24), True),
                                             (timedelta(hours=24, seconds=1), False)])
def test_trade_out_freshness_window(age, fresh):
    out = trade_out(row(status="open", mark=110, mark_at=NOW - age), NOW)
    assert out["quote_status"] == ("available" if fresh else "sin_datos")
    assert out["mark_price"] == (Decimal(110) if fresh else None)
    assert out["unrealized_pnl"] == (Decimal(20) if fresh else None)
    assert (out["market_label"], out["quantity_label"]) == ("dato", "supuesto")
    assert out["realized_pnl"] is None and out["realized_pnl_net"] is None
    assert "tenant_id" not in out


def test_trade_out_closed_keeps_mark_and_has_no_unrealized():
    closed = row(exit_=120, mark=120, mark_at=NOW - timedelta(minutes=5), entry_fee=Decimal(1), exit_fee=Decimal(1))
    closed.cost_assumption_version = "v"
    out = trade_out(closed, NOW)
    assert out["mark_price"] == Decimal(120)
    assert out["unrealized_pnl"] is None and out["unrealized_pnl_net"] is None
    assert (out["realized_pnl"], out["realized_pnl_net"]) == (Decimal(40), Decimal(38))
    assert out["cost_label"] is not None
    stale = row(exit_=120, mark=120, mark_at=NOW - timedelta(days=3))
    assert trade_out(stale, NOW)["mark_price"] == Decimal(120)
    assert trade_out(stale, NOW)["cost_label"] is None


def _quote(price, at=NOW, currency="USD"):
    return {"live_c": price, "live_t": at.timestamp(), "currency": currency}


@pytest.mark.parametrize(("direction", "price", "reason"), [
    ("long", 90, "stop"), ("long", 120, "target"), ("short", 110, "stop"), ("short", 80, "target"),
])
def test_open_position_closes_exactly_at_the_level(direction, price, reason):
    trade = row(status="open", direction=direction, entry_fee=Decimal(1))
    trade.mark_at = None
    assert apply_quote(trade, _quote(price), NOW, costs=COSTS)
    assert (trade.status, trade.close_reason, trade.exit_price, trade.exit_at) == (
        "closed", reason, Decimal(price), NOW)
    assert trade.exit_fee == Decimal("1.000000")


def test_legacy_open_position_closes_without_inventing_an_exit_fee():
    trade = row(status="open")
    assert apply_quote(trade, _quote(90), NOW, costs=COSTS)
    assert trade.status == "closed" and trade.exit_fee is None


def test_short_pending_fills_exactly_at_the_proposed_entry():
    trade = row(status="pending", direction="short", entry=None)
    assert apply_quote(trade, _quote(100), NOW, costs=COSTS)
    assert (trade.status, trade.entry_price) == ("open", Decimal(100))


@pytest.mark.parametrize(("direction", "price", "stop", "target"), [
    ("long", 90, 90, 120),      # entra justo en el stop: entrada invalida
    ("short", 110, 110, 80),
])
def test_pending_gap_onto_the_stop_does_not_fill(direction, price, stop, target):
    trade = row(status="pending", direction=direction, entry=None, stop=stop, target=target,
                proposed=100 if direction == "long" else 100)
    if direction == "long":
        trade.proposed_entry = Decimal(95)
    else:
        trade.proposed_entry = Decimal(105)
    assert apply_quote(trade, _quote(price), NOW, costs=COSTS) is False
    assert trade.status == "pending"


@pytest.mark.parametrize(("age", "accepted"), [(timedelta(hours=24), True), (timedelta(hours=24, minutes=30), False)])
def test_quote_age_limit_is_24_hours(age, accepted):
    trade = row(status="open")
    assert apply_quote(trade, _quote(105, NOW - age), NOW) is accepted


@pytest.mark.parametrize(("price", "currency", "accepted"), [
    ("0.5", "USD", True), ("0", "USD", False), ("105", "ABCDEFGH", True), ("105", "ABCDEFGHI", False),
])
def test_quote_price_and_currency_guards(price, currency, accepted):
    trade = row(status="open", currency=None, stop="0.1", target=200)
    assert apply_quote(trade, _quote(price, currency=currency), NOW) is accepted
    assert trade.status == "open"


@pytest.mark.parametrize(("entry_at", "due"), [
    (datetime(2026, 3, 1, 9, tzinfo=UTC), datetime(2031, 3, 1, 9, tzinfo=UTC)),
    (datetime(2028, 2, 29, 9, tzinfo=UTC), datetime(2033, 2, 28, 9, tzinfo=UTC)),
])
def test_five_year_horizon_deadline(entry_at, due):
    trade = row(status="open", horizon="five_years")
    trade.entry_at = entry_at
    assert deadline(trade) == due


def test_utc_normalizes_naive_and_aware():
    assert utc(datetime(2026, 1, 1, 10)) == datetime(2026, 1, 1, 10, tzinfo=UTC)
    from datetime import timezone
    madrid = timezone(timedelta(hours=2))
    assert utc(datetime(2026, 7, 1, 10, tzinfo=madrid)).hour == 8


def test_same_proposal_messages():
    existing = row(status="pending", entry=None)
    existing.proposal_currency_known = False
    proposal = PaperProposal(proposal_key="k", ticker="ASTS", direction="long", horizon="short",
                             thesis="Una tesis simulada con fuente y riesgos", conviction="0.8",
                             proposed_entry="100", stop="90", target="120", quantity="2",
                             inference_basis="Inferido a partir de los documentos oficiales")
    with pytest.raises(ValueError, match="^No se conoce la moneda original de esta propuesta histórica"):
        _same_proposal(existing, proposal)
    existing.proposal_currency_known = True
    existing.proposal_currency = "EUR"
    with pytest.raises(ValueError, match="^La clave ya pertenece a otra propuesta$"):
        _same_proposal(existing, proposal)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="paper-r3"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_refresh_updates_open_positions_and_counts(db):
    now = datetime.now(UTC)
    opened = row(status="open", ticker="AAA")
    opened.created_at, opened.entry_at = now - timedelta(days=3), now - timedelta(days=2)
    other = row(status="open", ticker="BBB")
    other.created_at, other.entry_at = now - timedelta(days=3), now - timedelta(days=2)
    db.add_all([opened, other])
    db.commit()
    quotes = {"AAA": _quote(105, now - timedelta(minutes=1)), "BBB": {}}
    assert refresh_trades(db, quotes.__getitem__) == {"updated": 1, "unchanged": 1, "symbols_checked": 2}
    db.refresh(opened)
    assert opened.mark_price == Decimal(105)


def test_refresh_caps_symbols_but_keeps_rows_of_already_quoted_symbols(db):
    now = datetime.now(UTC)
    rows = []
    for i in range(52):
        ticker = f"T{i}" if i < 51 else "T0"
        trade = row(status="open", ticker=ticker)
        trade.created_at, trade.entry_at = now - timedelta(days=3), now - timedelta(days=2)
        trade.updated_at = now - timedelta(hours=52 - i)
        rows.append(trade)
    db.add_all(rows)
    db.commit()
    seen = []

    def fetch(ticker):
        seen.append(ticker)
        return _quote(105, now - timedelta(minutes=1))

    result = refresh_trades(db, fetch)
    assert result["symbols_checked"] == 50 and len(seen) == 50 and "T50" not in seen
    assert result["updated"] == 51  # 50 simbolos + la segunda fila de T0
