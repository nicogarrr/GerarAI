"""Invariantes del FIFO fiscal (``replay_tax_fifo``) buscadas con Hypothesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.services.tax_report_service import (
    WASH_SALE_WINDOW,
    _fifo_sort_key,
    replay_tax_fifo,
)

D0 = date(2023, 1, 2)


@dataclass
class Tx:
    action: str
    quantity: Decimal
    price: Decimal
    fees: Decimal
    trade_date: date
    id: int
    currency: str = "EUR"
    raw_payload: dict = field(default_factory=dict)


qty = st.integers(min_value=1, max_value=50).map(Decimal)
price = st.integers(min_value=1, max_value=400).map(lambda c: Decimal(c) / 2)
fees = st.integers(min_value=0, max_value=5).map(Decimal)


@st.composite
def ledgers(draw, max_events=12, allow_over_sell=True):
    n = draw(st.integers(min_value=1, max_value=max_events))
    day = D0
    events = []
    held = Decimal("0")
    for i in range(n):
        day = day + timedelta(days=draw(st.integers(min_value=0, max_value=50)))
        buy = draw(st.booleans()) or (not allow_over_sell and held == 0)
        q = draw(qty)
        if not buy and not allow_over_sell:
            q = min(q, held)
        events.append(Tx("buy" if buy else "sell", q, draw(price), draw(fees), day, i + 1))
        held = held + q if buy else max(held - q, Decimal("0"))
    return sorted(events, key=_fifo_sort_key)


def one(_currency, _day):
    return Decimal("1")


def replay(events, rate=one):
    return replay_tax_fifo(events, rate, date(1900, 1, 1), date(2999, 12, 31))


@given(ledgers())
def test_lots_never_negative_and_shares_conserved(events):
    lots, sales = replay(events)
    held = Decimal("0")
    for tx in events:
        held = held + tx.quantity if tx.action == "buy" else max(held - tx.quantity, Decimal("0"))
    assert sum((lot["qty"] for lot in lots), Decimal("0")) == held
    for lot in lots:
        assert lot["qty"] > 0
        assert 0 <= lot["capacity"] <= lot["qty"] or lot["capacity"] >= 0
        assert lot["deferred"] >= 0
        assert lot["deferred_base"] is None or lot["deferred_base"] >= 0
    for entry in sales:
        sale = entry["sale"]
        q = entry["transaction"].quantity
        assert entry["over_sell_quantity"] >= 0
        assert entry["over_sell"] == (entry["over_sell_quantity"] > 0)
        if sale is not None:
            assert 0 <= sale["blocked_qty"] <= q
            assert sale["blocked_qty"] + sale["qty_unblocked"] == q


@given(ledgers(allow_over_sell=False))
def test_cost_is_conserved_through_sales_and_wash_deferrals(events):
    """Coste de compra + perdidas diferidas = coste vendido + coste que queda."""
    lots, sales = replay(events)
    bought = sum((tx.quantity * tx.price + tx.fees for tx in events if tx.action == "buy"), Decimal("0"))
    deferred_in = sum(
        (e["sale"]["blocked_qty"] * e["sale"]["loss_per_share"] for e in sales if e["sale"]),
        Decimal("0"),
    )
    sold_cost = sum((e["cost_native"] for e in sales), Decimal("0"))
    left = sum((lot["qty"] * lot["unit"] + lot["deferred"] for lot in lots), Decimal("0"))
    assert abs((bought + deferred_in) - (sold_cost + left)) < Decimal("1e-12")


@given(ledgers())
def test_rate_one_makes_base_equal_native(events):
    _, sales = replay(events)
    for e in sales:
        if e.get("cost_unknown"):
            # coste heredado de una venta descubierta: en euros es N/D a proposito
            assert e["cost_base"] is None and e["gain_base_raw"] is None
            continue
        assert e["gain_base_raw"] == e["gain_native"]
        assert e["cost_base"] == e["cost_native"]


@given(ledgers(allow_over_sell=False), st.data())
def test_unknown_buy_rate_makes_the_sale_cost_unknown(events, data):
    buys = [tx for tx in events if tx.action == "buy"]
    missing = data.draw(st.sampled_from(buys)).trade_date

    def rate(_currency, day):
        return None if day == missing else Decimal("1")

    _, sales = replay(events, rate)
    _, known = replay(events)
    for e, k in zip(sales, known, strict=True):
        if e["transaction"].trade_date == missing:
            assert e["proceeds_base"] is None and e["gain_base_raw"] is None
        if e["cost_base"] is not None:
            assert e["cost_base"] == k["cost_base"]


@given(ledgers())
def test_buys_outside_both_windows_never_block_a_loss(events):
    _, sales = replay(events)
    buy_days = [tx.trade_date for tx in events if tx.action == "buy"]
    for e in sales:
        sale = e["sale"]
        if sale is None:
            continue
        d = sale["date"]
        if not any(d - WASH_SALE_WINDOW <= b <= d + WASH_SALE_WINDOW for b in buy_days):
            assert sale["blocked_qty"] == 0


@st.composite
def over_sell_then_repurchase(draw):
    """Compra, venta descubierta con perdida, recompra dentro de 2 meses y venta."""
    held = draw(st.integers(min_value=0, max_value=20))
    extra = draw(st.integers(min_value=1, max_value=10))
    buy_price = draw(st.integers(min_value=50, max_value=200))
    sell_price = draw(st.integers(min_value=1, max_value=buy_price - 1))
    d1 = D0 + timedelta(days=draw(st.integers(1, 30)))
    d2 = d1 + timedelta(days=draw(st.integers(1, 55)))
    d3 = d2 + timedelta(days=draw(st.integers(1, 400)))
    events = []
    if held:
        events.append(Tx("buy", Decimal(held), Decimal(buy_price), Decimal(0), D0, 1))
    events += [
        Tx("sell", Decimal(held + extra), Decimal(sell_price), Decimal(0), d1, 2),
        Tx("buy", Decimal(draw(st.integers(1, 30))), Decimal(draw(st.integers(1, 300))), Decimal(0), d2, 3),
    ]
    events.append(Tx("sell", events[-1].quantity, Decimal(draw(st.integers(1, 300))), Decimal(0), d3, 4))
    return events


@given(over_sell_then_repurchase())
def test_a_loss_born_from_an_over_sell_never_reaches_a_known_cost(events):
    """Una venta descubierta tiene coste desconocido, luego su perdida tambien.

    Si esa perdida (calculada con coste cero en el exceso) se difiere al lote
    recomprado, la venta futura de ese lote no puede publicar coste ni
    resultado en euros como si fuesen conocidos.
    """
    _, sales = replay(events)
    over, last = sales[0], sales[-1]
    assert over["over_sell"]
    if over["sale"] is not None and over["sale"]["blocked_qty"] > 0:
        assert last["cost_unknown"] is True
        assert last["cost_base"] is None and last["gain_base_raw"] is None
    if not last["cost_unknown"]:
        assert last["cost_base"] is not None
