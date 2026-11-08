"""Backtest point-in-time del motor de TIR: sin mirar al futuro, primera cifra publicada, splits y métricas."""
from __future__ import annotations

from datetime import date

import pytest

from app.valuation import irr_pit_backtest as bt


def _payload(rows):
    """companyfacts mínimo: rows = (concept, start, end, val, filed, form)."""
    facts: dict = {"us-gaap": {}}
    for concept, start, end, val, filed, form in rows:
        node = facts["us-gaap"].setdefault(concept, {"units": {"USD": []}})
        r = {"end": end, "val": val, "filed": filed, "form": form}
        if start:
            r["start"] = start
        node["units"]["USD"].append(r)
    return {"facts": facts}


REV = [
    ("Revenues", "2014-01-01", "2014-12-31", 80e6, "2015-02-20", "10-K"),
    ("Revenues", "2015-01-01", "2015-12-31", 100e6, "2016-02-20", "10-K"),
    # re-expresión publicada un año después: el backtest debe usar la primera cifra
    ("Revenues", "2015-01-01", "2015-12-31", 90e6, "2017-02-20", "10-K"),
    ("Revenues", "2016-01-01", "2016-12-31", 120e6, "2017-02-20", "10-K"),
]


def test_facts_filed_on_or_after_t_are_excluded_and_the_guard_trips():
    facts = bt.facts_from_companyfacts(_payload(REV))
    t = date(2016, 6, 30)
    seen = bt.as_of(facts, t)
    assert seen and all(f.filed < t for f in seen)
    assert max(f.filed for f in seen) == date(2016, 2, 20)
    with pytest.raises(bt.LookAheadError):
        bt.assert_point_in_time(facts, t)  # la lista completa trae hechos de 2017
    bt.assert_point_in_time(seen, t)


def test_annual_series_uses_first_published_value_not_restatement():
    facts = bt.facts_from_companyfacts(_payload(REV))
    assert bt.annual(bt.as_of(facts, date(2016, 1, 31)), "revenue") == {2014: 80.0}
    assert bt.annual(bt.as_of(facts, date(2016, 6, 30)), "revenue") == {2014: 80.0, 2015: 100.0}
    later = bt.annual(bt.as_of(facts, date(2018, 6, 30)), "revenue")
    assert later == {2014: 80.0, 2015: 100.0, 2016: 120.0}  # no 90 (re-expresado en 2017)


def test_quarterly_rows_never_enter_the_annual_series():
    rows = REV + [("Revenues", "2016-01-01", "2016-03-31", 30e6, "2016-05-01", "10-Q")]
    facts = bt.facts_from_companyfacts(_payload(rows))
    assert 2016 not in bt.annual(bt.as_of(facts, date(2016, 6, 30)), "revenue")


def test_split_between_share_period_and_t_rescales_shares():
    splits = [(date(2022, 6, 6), 20.0)]
    assert bt.split_factor(splits, date(2021, 12, 31), date(2022, 6, 30)) == 20.0
    assert bt.split_factor(splits, date(2021, 12, 31), date(2022, 6, 1)) == 1.0
    # el cierre «ajustado por splits» de hoy se des-ajusta al precio que cotizaba en t
    assert bt.split_factor(splits, date(2019, 12, 31), date(2026, 11, 1)) == 20.0


def test_total_shareholder_return_includes_dividends_via_adjusted_close():
    days = [date(2015, 6, 30), date(2016, 6, 30), date(2018, 6, 29), date(2020, 6, 30)]
    adj = [100.0, 110.0, 133.1, 161.051]
    series = list(zip(days, adj, strict=True))
    assert bt.total_return(series, date(2015, 6, 30), 1) == pytest.approx(0.10)
    assert bt.total_return(series, date(2015, 6, 30), 5) == pytest.approx(0.10)
    assert bt.total_return(series, date(2016, 6, 30), 5) is None  # aún no hay 5 años de datos


def test_rank_ic_and_newey_west():
    assert bt.rank_ic([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert bt.rank_ic([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    t0 = bt.newey_west_t([0.1, -0.1] * 10, lags=2)
    assert abs(t0) < 1e-9
    assert bt.newey_west_t([0.10, 0.12, 0.08, 0.11, 0.09, 0.10], lags=1) > 5
    lo, hi = bt.block_bootstrap_ci([0.1, 0.12, 0.08, 0.11, 0.09, 0.10], block=2, n=500, seed=1)
    assert lo < 0.1 < hi


def test_point_in_time_inputs_run_through_the_real_engine():
    rows = []
    for y, rev, oi, da, ocf, capex in [(2013, 900, 180, 40, 170, 50), (2014, 1000, 200, 45, 190, 55),
                                         (2015, 1100, 225, 50, 210, 60)]:
        filed = f"{y + 1}-02-20"
        span = (f"{y}-01-01", f"{y}-12-31")
        rows += [("Revenues", *span, rev * 1e6, filed, "10-K"),
                 ("OperatingIncomeLoss", *span, oi * 1e6, filed, "10-K"),
                 ("DepreciationDepletionAndAmortization", *span, da * 1e6, filed, "10-K"),
                 ("NetCashProvidedByUsedInOperatingActivities", *span, ocf * 1e6, filed, "10-K"),
                 ("PaymentsToAcquirePropertyPlantAndEquipment", *span, capex * 1e6, filed, "10-K"),
                 ("NetIncomeLoss", *span, oi * 0.7e6, filed, "10-K")]
    payload = _payload(rows)
    payload["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {"shares": [
        {"start": "2015-01-01", "end": "2015-12-31", "val": 100e6, "filed": "2016-02-20", "form": "10-K"}]}}
    payload["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"] = {"units": {"USD": [
        {"end": "2015-12-31", "val": 50e6, "filed": "2016-02-20", "form": "10-K"},
        {"end": "2016-03-31", "val": 999e6, "filed": "2016-07-30", "form": "10-Q"}]}}  # posterior a t
    facts = bt.facts_from_companyfacts(payload)
    t = date(2016, 6, 30)
    inp = bt.build_inputs(bt.as_of(facts, t), t=t, price=27.5, splits=[], financial=False)
    assert inp.start.cash == pytest.approx(50.0)
    assert inp.start.shares_diluted == pytest.approx(100.0)
    assert inp.start.basis == "ev_ebitda"
    assert inp.history.years == [2013, 2014, 2015]
    out = bt.value(inp, peer_multiples=())
    assert out["base"] is not None and out["bear"] <= out["base"] <= out["bull"]


def test_missing_diluted_shares_fall_back_to_net_income_over_diluted_eps_like_the_product():
    rows = [("Revenues", "2015-01-01", "2015-12-31", 1000e6, "2016-02-20", "10-K"),
            ("NetIncomeLoss", "2015-01-01", "2015-12-31", 200e6, "2016-02-20", "10-K")]
    payload = _payload(rows)
    payload["facts"]["us-gaap"]["EarningsPerShareDiluted"] = {"units": {"USD/shares": [
        {"start": "2015-01-01", "end": "2015-12-31", "val": 2.5, "filed": "2016-02-20", "form": "10-K"}]}}
    payload["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"] = {"units": {"USD": [
        {"end": "2015-12-31", "val": 20e6, "filed": "2016-02-20", "form": "10-K"}]}}  # sin caja se descarta la fecha
    t = date(2016, 6, 30)
    inp = bt.build_inputs(bt.as_of(bt.facts_from_companyfacts(payload), t), t=t, price=30.0, splits=[],
                          financial=True)
    assert inp.start.shares_diluted == pytest.approx(80.0)
    assert any("BPA" in w for w in inp.warnings)


def test_shares_tagged_without_scale_are_caught_by_the_cover_page_filed_before_t():
    rows = [("Revenues", "2015-01-01", "2015-12-31", 40e6, "2016-03-01", "10-K"),
            ("NetIncomeLoss", "2015-01-01", "2015-12-31", 8e6, "2016-03-01", "10-K")]
    payload = _payload(rows)
    payload["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {"shares": [
        {"start": "2015-01-01", "end": "2015-12-31", "val": 9609, "filed": "2016-03-01", "form": "10-K"}]}}
    payload["facts"]["dei"] = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2016-02-20", "val": 9_650_000, "filed": "2016-03-01", "form": "10-K"},
        {"end": "2016-08-01", "val": 1, "filed": "2016-08-05", "form": "10-Q"}]}}}  # posterior a t
    payload["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"] = {"units": {"USD": [
        {"end": "2015-12-31", "val": 20e6, "filed": "2016-02-20", "form": "10-K"}]}}  # sin caja se descarta la fecha
    t = date(2016, 6, 30)
    inp = bt.build_inputs(bt.as_of(bt.facts_from_companyfacts(payload), t), t=t, price=30.0, splits=[],
                          financial=True)
    assert inp.start.shares_diluted == pytest.approx(9.65)
    assert any("portada" in w for w in inp.warnings)


def test_concepts_start_with_the_product_ingestion_map():
    from app.services.financial_ingestion_service import SEC_METRIC_MAP

    prod = {m: list(c) for m, c, _ in SEC_METRIC_MAP}
    assert list(bt.CONCEPTS["depreciation_amortization"][:len(prod["depreciation_amortization"])]) == \
        prod["depreciation_amortization"]
    assert "Depreciation" in bt.CONCEPTS["depreciation_amortization"]
    assert "WeightedAverageNumberOfShareOutstandingBasicAndDiluted" in bt.CONCEPTS["shares_diluted"]


def test_ifrs_profit_attributable_to_parent_beats_consolidated_profit():
    payload = {"facts": {"ifrs-full": {
        "Revenue": {"units": {"USD": [{"start": "2018-01-01", "end": "2018-12-31", "val": 60e9, "filed": "2019-03-29",
                                       "form": "40-F"}]}},
        "ProfitLoss": {"units": {"USD": [{"start": "2018-01-01", "end": "2018-12-31", "val": 7e9,
                                          "filed": "2019-03-29", "form": "40-F"}]}},
        "ProfitLossAttributableToOwnersOfParent": {"units": {"USD": [
            {"start": "2018-01-01", "end": "2018-12-31", "val": 3.5e9, "filed": "2019-03-29", "form": "40-F"}]}},
    }}}
    facts = bt.as_of(bt.facts_from_companyfacts(payload), date(2019, 6, 30))
    assert bt.annual(facts, "net_income") == {2018: 3500.0}


def test_ifrs_product_map_is_merged_after_the_us_gaap_one():
    from app.services.financial_ingestion_service import SEC_IFRS_METRIC_MAP

    ifrs = {m: list(c) for m, c, _ in SEC_IFRS_METRIC_MAP}
    for concept in ifrs.get("revenue", []):
        assert concept in bt.CONCEPTS["revenue"]
    assert "RevenueFromContractsWithCustomers" in bt.CONCEPTS["revenue"]
