"""Supervivientes de mutacion en ``tax_report_service`` (ronda 3): lectura de informes.

``cancelled_buy_dates`` / ``flag_cancelled_lot_sales`` (compras anuladas por el
broker) y las copias de lectura ``sanitize_realized_over_sells`` /
``sanitize_summary_over_sells`` de informes persistidos antiguos con ventas
descubiertas. Fija el comportamiento ACTUAL; no cambia ninguna regla fiscal.
"""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.tax_report_service import (
    cancelled_buy_dates,
    flag_cancelled_lot_sales,
    sanitize_realized_over_sells,
    sanitize_summary_over_sells,
)


def _ev(action, day, payload=None):
    return SimpleNamespace(action=action, trade_date=day, raw_payload=payload)


D1, D2, D3 = date(2026, 1, 10), date(2026, 2, 10), date(2026, 3, 10)


@pytest.mark.parametrize("action", ["cancelled", "CANCELLED", "Cancelled"])
def test_cancelled_action_is_case_insensitive(action):
    assert cancelled_buy_dates([_ev(action, D1)]) == [D1]


@pytest.mark.parametrize("action", [None, "", "buy", "cancel", "sell"])
def test_non_cancelled_actions_are_ignored(action):
    assert cancelled_buy_dates([_ev(action, D1)]) == []


@pytest.mark.parametrize("side", ["SELL", "sell", "Sold", "S", " sell ", "SELL (Ca.)", "sell(x)"])
def test_cancelled_sells_are_not_cancelled_buys(side):
    assert cancelled_buy_dates([_ev("cancelled", D1, {"buySell": side})]) == []


@pytest.mark.parametrize("payload", [None, "not a dict", ["sell"], {}, {"buySell": None},
                                     {"buySell": "BUY"}, {"buySell": "BUY (Ca.)"},
                                     {"buySell": "xs"}, {"buySell": "seller"}])
def test_unknown_or_buy_side_counts_as_cancelled_buy(payload):
    assert cancelled_buy_dates([_ev("cancelled", D1, payload)]) == [D1]


def test_cancelled_dates_keep_order_and_skip_sells():
    events = [
        _ev("cancelled", D2, {"buySell": "BUY"}),
        _ev("buy", D1),
        _ev("cancelled", D1, {"buySell": "SELL"}),
        _ev("cancelled", D3),
    ]
    assert cancelled_buy_dates(events) == [D2, D3]


def test_flag_cancelled_lot_sales_marks_sales_on_or_after_the_cancellation():
    events = [_ev("cancelled", D2)]
    sales = [{"transaction": SimpleNamespace(trade_date=d)} for d in (D1, D2, D3)]
    flag_cancelled_lot_sales(events, sales)
    assert [s["cancelled_lot"] for s in sales] == [False, True, True]


def test_flag_cancelled_lot_sales_without_cancellations_is_false():
    sales = [{"transaction": SimpleNamespace(trade_date=D3)}]
    flag_cancelled_lot_sales([_ev("buy", D1), _ev("cancelled", D1, {"buySell": "SELL"})], sales)
    assert sales[0]["cancelled_lot"] is False


COST_KEYS = ("cost_native", "cost_base", "gain_native", "gain_base", "raw_gain_native")


def _sale(over_sell=False):
    sale = dict.fromkeys(COST_KEYS, 10)
    sale["proceeds_native"] = 50
    if over_sell is not None:
        sale["over_sell"] = over_sell
    return sale


def _bucket(ticker="AAA", over_sell=None, sales=()):
    bucket = {"ticker": ticker, "cost_native": 1, "gain_native": 2, "gain_base": 3,
              "proceeds_native": 4, "sales": list(sales)}
    if over_sell is not None:
        bucket["over_sell"] = over_sell
    return bucket


def test_realized_sale_over_sell_nulls_only_that_sale_and_the_bucket_totals():
    realized = [_bucket(sales=[_sale(True), _sale(False)]), _bucket("BBB", sales=[_sale(False)])]
    before = deepcopy(realized)
    out = sanitize_realized_over_sells(realized)
    assert realized == before  # el JSON persistido no se toca
    affected, clean = out
    assert all(affected["sales"][0][k] is None for k in COST_KEYS)
    assert affected["sales"][0]["proceeds_native"] == 50
    assert all(affected["sales"][1][k] == 10 for k in COST_KEYS)
    assert (affected["cost_native"], affected["gain_native"], affected["gain_base"]) == (None, None, None)
    assert affected["proceeds_native"] == 4
    assert clean == before[1]


def test_realized_bucket_flag_alone_nulls_bucket_totals_but_not_sales():
    out = sanitize_realized_over_sells([_bucket(over_sell=True, sales=[_sale(None)])])
    bucket = out[0]
    assert (bucket["cost_native"], bucket["gain_native"], bucket["gain_base"]) == (None, None, None)
    assert all(bucket["sales"][0][k] == 10 for k in COST_KEYS)


def test_realized_bucket_without_sales_key_and_false_flag_is_untouched():
    bucket = {"ticker": "AAA", "cost_native": 1, "gain_native": 2, "gain_base": 3, "over_sell": False}
    assert sanitize_realized_over_sells([bucket]) == [dict(bucket)]


def test_summary_unchanged_when_no_over_sell_and_is_a_copy():
    summary = {"total_realized_gain_base": 100, "net_taxable_base": 90}
    out = sanitize_summary_over_sells(summary, [_bucket(sales=[_sale(False)]), _bucket(over_sell=False)])
    assert out == summary and out is not summary


@pytest.mark.parametrize("summary", [None, {}])
def test_summary_none_or_empty_without_realized(summary):
    assert sanitize_summary_over_sells(summary, []) == {}
    assert sanitize_summary_over_sells(summary, None) == {}


def test_summary_bucket_over_sell_nulls_totals_and_lists_tickers_sorted():
    summary = {"total_realized_gain_base": 100, "net_taxable_base": 90, "other": 7, "over_sell": ["ZZZ"]}
    realized = [
        _bucket("MMM", sales=[_sale(True)]),
        _bucket("CCC", over_sell=True),
        _bucket("OKK", sales=[_sale(False)]),
        _bucket(None, over_sell=True),
        _bucket("", over_sell=True),
    ]
    out = sanitize_summary_over_sells(summary, realized)
    assert out["total_realized_gain_base"] is None
    assert out["net_taxable_base"] is None
    assert out["other"] == 7
    assert out["over_sell"] == ["CCC", "MMM", "ZZZ"]
    assert summary["total_realized_gain_base"] == 100  # original intacto
    assert summary["over_sell"] == ["ZZZ"]


def test_summary_sale_level_over_sell_alone_flags_the_ticker():
    out = sanitize_summary_over_sells({"net_taxable_base": 5}, [_bucket("AAA", sales=[_sale(True)])])
    assert out == {"net_taxable_base": None, "total_realized_gain_base": None, "over_sell": ["AAA"]}


def test_summary_over_sell_list_dedupes():
    out = sanitize_summary_over_sells({"over_sell": ["AAA"]}, [_bucket("AAA", over_sell=True)])
    assert out["over_sell"] == ["AAA"]


def test_summary_bucket_level_flag_alone_nulls_the_totals():
    out = sanitize_summary_over_sells({"net_taxable_base": 5}, [_bucket("AAA", over_sell=True)])
    assert out["net_taxable_base"] is None
    assert out["over_sell"] == ["AAA"]


def test_summary_and_realized_tolerate_buckets_without_sales():
    realized = [{"ticker": "AAA", "gain_base": 1}]
    assert sanitize_summary_over_sells({"net_taxable_base": 5}, realized) == {"net_taxable_base": 5}
    assert sanitize_realized_over_sells(realized) == realized
