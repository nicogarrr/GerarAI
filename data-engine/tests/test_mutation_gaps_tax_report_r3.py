"""Supervivientes de mutacion en ``tax_report_service`` (ronda 3): helpers.

Hora de ejecucion (orden FIFO del mismo dia y del libro de divisas), salida a
prorrata del diferido, ventana hacia atras de la recompra (regla de los dos
meses, con la excepcion de la compra inicial unica) y etiquetas de caja sin
emisor. Fija el comportamiento ACTUAL; no cambia ninguna regla fiscal.
"""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.services.tax_report_service import (
    _execution_time,
    _fx_time,
    _raw_action_label,
    _release_deferred,
    _unattributed_label,
    backward_repurchase_quantity,
)


def _tx(payload=None, **kw):
    return SimpleNamespace(raw_payload=payload, **kw)


@pytest.mark.parametrize(("raw", "expected"), [
    ("20260115;103015", "103015"),
    ("2026-01-15 10:30:45 EST", "103045"),
    ("2026-01-15T10:30", "103000"),
    ("20260115", ""),
])
def test_execution_time_from_flex_datetime(raw, expected):
    assert _execution_time(_tx({"dateTime": raw})) == expected


@pytest.mark.parametrize(("payload", "expected"), [
    ({"dateTime": "20260115;091500", "tradeTime": "120000"}, "091500"),  # dateTime manda
    ({"tradeTime": "10:30"}, "103000"),
    ({"tradeTime": "103015123"}, "103015"),
    ({"tradeTime": "1030"}, "103000"),
    ({"tradeTime": "103"}, ""),
    ({"tradeTime": None}, ""),
    ({}, ""),
    (None, ""),
    ("20260115;103000", ""),  # payload que no es un dict
])
def test_fx_time_falls_back_to_trade_time(payload, expected):
    assert _fx_time(_tx(payload)) == expected


def test_release_deferred_on_an_empty_lot_returns_zero():
    lot = {"qty": D("0"), "deferred": D("50"), "deferred_base": D("40")}
    released = _release_deferred(lot, D("1"))
    assert released == D("0") and isinstance(released, D)
    assert lot["deferred"] == D("50") and lot["deferred_base"] == D("40")


def test_release_deferred_without_deferral_returns_decimal_zero():
    lot = {"qty": D("10"), "deferred": D("0"), "deferred_base": D("0")}
    released = _release_deferred(lot, D("4"))
    assert released == D("0") and isinstance(released, D)


def test_release_deferred_is_pro_rata_in_both_currencies():
    lot = {"qty": D("10"), "deferred": D("50"), "deferred_base": D("40")}
    assert _release_deferred(lot, D("4")) == D("20")
    assert (lot["deferred"], lot["deferred_base"]) == (D("30"), D("24"))


SALE = date(2026, 10, 27)
START = date(2026, 8, 27)  # SALE - 2 meses


def _lot(day, qty, capacity=None):
    return {"date": day, "qty": D(qty), "capacity": D(capacity if capacity is not None else qty)}


def test_purchase_on_the_window_start_is_inside_the_window():
    buys = [(date(2026, 1, 10), D(100)), (START, D(30))]
    assert backward_repurchase_quantity(buys, [], [_lot(START, 30)], SALE, D(100)) == D(30)


def test_single_initial_purchase_on_the_window_start_is_the_exception():
    assert backward_repurchase_quantity([(START, D(30))], [], [_lot(START, 30)], SALE, D(10)) == D(0)


def test_sale_on_the_window_start_does_not_reduce_prior_holdings():
    buys = [(date(2026, 1, 10), D(10)), (date(2026, 9, 1), D(5))]
    sells = [(START, D(10))]
    assert backward_repurchase_quantity(buys, sells, [_lot(date(2026, 9, 1), 5)], SALE, D(10)) == D(5)


def test_lot_on_the_window_start_is_eligible():
    buys = [(date(2026, 1, 10), D(100)), (START, D(30)), (date(2026, 9, 1), D(5))]
    lots = [_lot(START, 30), _lot(date(2026, 9, 1), 5)]
    assert backward_repurchase_quantity(buys, [], lots, SALE, D(100)) == D(35)


@pytest.mark.parametrize(("quantity", "lots", "buys", "expected"), [
    (D(4), [_lot(date(2026, 9, 1), 20)], [(date(2026, 9, 1), D(20))], D(4)),           # manda la venta
    (D(50), [_lot(date(2026, 9, 1), 20, capacity=6)], [(date(2026, 9, 1), D(20))], D(6)),  # capacidad
    (D(50), [_lot(date(2026, 9, 1), 20), _lot(date(2026, 9, 2), 20)],
     [(date(2026, 9, 1), D(20)), (date(2026, 9, 2), D(3))], D(23)),                     # compras en ventana
])
def test_blocked_quantity_is_the_minimum_of_the_three(quantity, lots, buys, expected):
    prior = [(date(2026, 1, 10), D(100))] + buys
    assert backward_repurchase_quantity(prior, [], lots, SALE, quantity) == expected


def test_unattributed_label_prefers_the_raw_symbol():
    assert _unattributed_label(_tx({"underlyingSymbol": " vod "}, currency="GBP", action="dividend")) == "UNATTRIBUTED:VOD"
    assert _unattributed_label(_tx({"Symbol": "", "other": "x"}, currency="GBP", action="dividend")) == "UNATTRIBUTED:GBP:dividend"
    assert _unattributed_label(_tx(None, currency=None, action=None)) == "UNATTRIBUTED:???:?"


def test_raw_action_label_reads_type_then_transaction_type():
    assert _raw_action_label(_tx({"type": "Payment In Lieu Of Dividends"}, action="dividend")) == "Payment In Lieu Of Dividends"
    assert _raw_action_label(_tx({"transactionType": "Return of Capital"}, action="dividend")) == "Return of Capital"
    assert _raw_action_label(_tx({}, action="dividend")) == "dividend"
