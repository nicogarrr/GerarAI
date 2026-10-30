"""FIFO fiscal: tras liquidar todo, resultado computable + pérdidas bloqueadas = ventas - compras."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.tax_report_service import _fifo_sort_key, replay_tax_fifo

D0 = date(2024, 1, 1)


def tx(i, action, day, qty, price, fees="0"):
    return SimpleNamespace(
        id=i,
        action=action,
        trade_date=D0 + timedelta(days=day),
        quantity=Decimal(qty),
        price=Decimal(price),
        fees=Decimal(fees),
        currency="EUR",
        raw_payload={},
    )


ops = st.lists(
    st.tuples(
        st.sampled_from(["buy", "sell"]),
        st.integers(0, 400),
        st.integers(1, 50),
        st.integers(1, 200),
        st.integers(0, 3),
    ),
    min_size=1,
    max_size=14,
)


@settings(max_examples=400, deadline=None, derandomize=True)
@given(ops)
def test_conservation(seq):
    events, held, n = [], 0, 0
    for k, (a, day, q, p, f) in enumerate(sorted(seq, key=lambda s: s[1])):
        if a == "sell":
            q = min(q, held)
            if q == 0:
                continue
            held -= q
        else:
            held += q
        events.append(tx(k + 1, a, day, q, p, f))
    events.sort(key=_fifo_sort_key)
    # liquidate everything far in the future so no deferral survives
    if held:
        events.append(tx(999, "sell", 2000, held, 10, 0))
    lots, sales = replay_tax_fifo(events, lambda c, d: Decimal(1), date(2000, 1, 1), date(2100, 1, 1))
    P = sum(e.quantity * e.price - e.fees for e in events if e.action == "sell")
    C = sum(e.quantity * e.price + e.fees for e in events if e.action == "buy")
    assert not lots
    assert not any(s["over_sell"] for s in sales)
    computable = Decimal(0)
    for s in sales:
        g = s["gain_native"]
        sale = s["sale"]
        if sale is not None:
            g += sale["blocked_qty"] * sale["loss_per_share"]
        computable += g
    assert abs(computable - (P - C)) < Decimal("1e-9"), (computable, P - C)
