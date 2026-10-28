"""Anulacion Flex posterior a una venta que consumio el lote anulado: revision manual."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.services.tax_report_service import (
    cancelled_buy_dates,
    flag_cancelled_lot_sales,
    replay_tax_fifo,
)


def tx(i, action, price, day, qty=1, payload=None):
    return SimpleNamespace(
        id=i, action=action, quantity=D(qty), price=D(price), fees=D(0),
        currency="USD", trade_date=day, raw_payload=payload or {},
    )


BUY, SELL = date(2025, 1, 1), date(2025, 6, 1)


def test_cancelled_buy_before_sale_is_detected():
    events = [
        tx(1, "cancelled", "10", BUY, payload={"buySell": "BUY", "cancelled_by": "C1"}),
        tx(2, "sell", "12", SELL),
        tx(3, "cancel", "10", date(2025, 7, 1), payload={"buySell": "BUY (Ca.)", "cancels": "T1"}),
    ]
    assert cancelled_buy_dates(events) == [BUY]
    _, sales = replay_tax_fifo(events, lambda c, d: D("1"), BUY, SELL)
    # El FIFO no resuelve el hueco: la venta queda descubierta, nunca con lote anulado.
    assert sales[0]["over_sell"] is True


def test_cancelled_sell_is_not_a_cancelled_lot():
    events = [tx(1, "cancelled", "12", SELL, payload={"buySell": "SELL"})]
    assert cancelled_buy_dates(events) == []


def test_sale_on_or_after_cancelled_buy_is_flagged_and_earlier_sale_is_not():
    early = date(2024, 12, 1)
    events = [
        tx(1, "buy", "9", date(2024, 11, 1)),
        tx(2, "sell", "11", early),
        tx(3, "cancelled", "10", BUY, payload={"buySell": "BUY"}),
        tx(4, "buy", "10", date(2025, 2, 1)),
        tx(5, "sell", "12", SELL),
    ]
    _, sales = replay_tax_fifo(events, lambda c, d: D("1"), date(2024, 1, 1), date(2025, 12, 31))
    flag_cancelled_lot_sales(events, sales)
    assert [(e["transaction"].id, e["cancelled_lot"]) for e in sales] == [(2, False), (5, True)]


def test_no_cancelled_buy_flags_nothing():
    events = [tx(1, "buy", "9", BUY), tx(2, "sell", "11", SELL)]
    _, sales = replay_tax_fifo(events, lambda c, d: D("1"), BUY, SELL)
    flag_cancelled_lot_sales(events, sales)
    assert sales[0]["cancelled_lot"] is False
