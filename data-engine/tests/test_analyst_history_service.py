"""Historial de analistas: puntuación sin mirar el futuro, muestra mínima,
encogimiento y caché/estados con Yahoo simulado (sin red)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import pytest

from app.services import analyst_history_service as svc

START = date(2020, 1, 1)
TODAY = date(2023, 6, 1)


def closes_linear(start: date, end: date, p0: float = 100.0, step: float = 0.1):
    out = []
    d, p = start, p0
    while d <= end:
        out.append((d, p))
        d += timedelta(days=1)
        p += step
    return out


def price_at(closes, day):
    return [c for d, c in closes if d <= day][-1]


def rec(firm, day, target, action="main"):
    return {
        "firm": firm,
        "date": datetime.combine(day, datetime.min.time()),
        "price_target": target,
        "grade_action": action,
    }


def test_target_scored_against_close_at_horizon_without_lookahead() -> None:
    closes = closes_linear(START, TODAY)
    targets = svc.normalize_targets([rec("A", date(2021, 1, 4), 200.0)], [])
    scored = svc.score_targets(targets, closes, TODAY)
    row = scored["12m"][0]
    end = date(2021, 1, 4) + timedelta(days=365)
    assert row["price_at_horizon"] == pytest.approx(price_at(closes, end))
    # Cambiar TODOS los cierres posteriores al horizonte no cambia nada.
    tampered = [(d, c * 7 if d > end else c) for d, c in closes]
    again = svc.score_targets(targets, tampered, TODAY)["12m"][0]
    assert again["logerr"] == pytest.approx(row["logerr"])
    assert again["dir_hit"] == row["dir_hit"] is True


def test_horizon_not_matured_until_closes_reach_it() -> None:
    issued = date(2023, 1, 2)
    closes = closes_linear(START, TODAY)
    targets = svc.normalize_targets([rec("A", issued, 150.0)], [])
    scored = svc.score_targets(targets, closes, TODAY)
    assert scored["12m"] == []  # vence en 2024
    assert len(scored["6m"]) == 0  # 2023-07-03 > hoy
    # Aunque hubiera cierres futuros en la serie, «hoy» manda.
    future = closes_linear(START, date(2025, 1, 1))
    assert svc.score_targets(targets, future, TODAY)["6m"] == []


def test_targets_are_split_adjusted_and_deduplicated_per_firm_and_day() -> None:
    splits = [(date(2022, 6, 10), 10.0)]
    rows = svc.normalize_targets(
        [
            rec("Keybanc", date(2022, 5, 1), 1000.0),
            rec("KeyBanc", date(2022, 5, 1), 1200.0),  # mismo día, alias de firma
            rec("B", date(2022, 7, 1), 130.0),
            rec("C", date(2022, 7, 1), 0.0),  # sin objetivo
            rec(None, date(2022, 7, 1), 10.0),
        ],
        splits,
    )
    assert [(r["firm"], r["target"]) for r in rows] == [("KeyBanc", 120.0), ("B", 130.0)]


def test_rows_before_first_trade_belong_to_another_instrument() -> None:
    rows = svc.normalize_targets(
        [rec("A", date(2019, 1, 1), 10.0), rec("A", date(2021, 1, 1), 20.0)], [], date(2020, 1, 1)
    )
    assert [r["target"] for r in rows] == [20.0]


def _many(firm, n, ratio, first=date(2020, 2, 1)):
    return [rec(firm, first + timedelta(days=30 * i), None) | {"_ratio": ratio} for i in range(n)]


def _scored_world(spec):
    """spec: firm -> (n, ratio objetivo/precio-al-emitir)."""
    closes = closes_linear(START, TODAY, 100.0, 0.0)  # precio plano 100
    records = []
    for firm, (n, ratio) in spec.items():
        for i in range(n):
            records.append(rec(firm, date(2020, 2, 1) + timedelta(days=30 * i), 100.0 * ratio))
    targets = svc.normalize_targets(records, [])
    return svc.score_targets(targets, closes, TODAY)


def test_min_sample_flag_and_ranking_order() -> None:
    scored = _scored_world({"Precisa": (8, 1.02), "Media": (8, 1.2), "Mala": (8, 1.6), "Poca": (3, 1.0)})
    summary = svc.summarize_horizon("12m", scored["12m"])
    assert [f.firm for f in summary.top][0] == "Precisa"
    assert summary.bottom[0].firm == "Mala"
    assert summary.ranked_firms == 3 and summary.small_sample_firms == 1
    assert all(f.firm != "Poca" for f in summary.top + summary.bottom)
    ranked = {f.firm: f for f in svc.rank_firms(scored["12m"])}
    assert ranked["Poca"].small_sample is True and ranked["Precisa"].small_sample is False
    precisa, mala = ranked["Precisa"].relative_error, ranked["Mala"].relative_error
    assert precisa is not None and mala is not None
    assert precisa < 0 < mala


def test_shrinkage_pulls_small_samples_toward_ticker_mean() -> None:
    few = _scored_world({"X": (5, 1.6), "Y": (20, 1.0), "Z": (20, 1.0)})["12m"]
    many = _scored_world({"X": (20, 1.6), "Y": (20, 1.0), "Z": (20, 1.0)})["12m"]
    x_few = {f.firm: f for f in svc.rank_firms(few)}["X"]
    x_many = {f.firm: f for f in svc.rank_firms(many)}["X"]
    raw = 100 * (abs(__import__("math").log(1.6)) - 0.0)
    # Con 5 muestras y 5 pseudo-muestras, el error relativo queda a medio camino.
    assert x_few.relative_error is not None and x_many.relative_error is not None
    assert 0 < x_few.relative_error < x_many.relative_error < raw


def test_best_horizon_is_lower_backtest_error_and_simple_consensus() -> None:
    closes = closes_linear(START, TODAY, 100.0, 0.05)  # sube despacio
    records = [rec(f"F{i % 4}", date(2020, 3, 1) + timedelta(days=20 * i), 120.0) for i in range(55)]
    records.append(rec("F0", date(2023, 5, 1), 180.0))
    records.append(rec("F1", date(2023, 5, 2), 160.0, action="up"))
    out = svc.build_history("TST", records, closes, [], today=TODAY, fetched_at=1)
    errs = {h.horizon: h.median_abs_error_pct or 0.0 for h in out.horizons}
    assert out.best_horizon == min(errs, key=lambda k: errs[k])
    assert out.consensus is not None and out.consensus.method == "simple_mean"
    # Último objetivo de cada firma en 12 meses: F0=180, F1=160, F2/F3=120.
    assert out.consensus.firms == 4 and out.consensus.mean == pytest.approx((180 + 160 + 120 + 120) / 4)
    assert out.rating_changes is not None and out.rating_changes.upgrades == 1


def test_no_targets_is_empty_sin_datos() -> None:
    out = svc.build_history("ITX.MC", [], closes_linear(START, TODAY), [], today=TODAY, fetched_at=1)
    assert out.status == "empty" and out.note_code == "no_history" and out.horizons == []


def test_service_caches_and_never_caches_failures(monkeypatch) -> None:
    calls: list[str] = []
    closes = closes_linear(START, TODAY)

    def fake(symbol):
        calls.append(symbol)
        return {
            "records": [rec("A", date(2021, 1, 4), 150.0)],
            "closes": closes,
            "splits": [],
            "currency": "USD",
            "quote_type": "EQUITY",
            "first_trade_date": None,
        }

    monkeypatch.setattr(svc, "_fetch_sync", fake)
    service = svc.AnalystHistoryService()
    first = asyncio.run(service.get("tst", today=TODAY))
    second = asyncio.run(service.get("TST", today=TODAY))
    assert first.status == "available" and first is second and calls == ["TST"]

    def boom(symbol):
        calls.append(symbol)
        raise RuntimeError("yahoo caido")

    monkeypatch.setattr(svc, "_fetch_sync", boom)
    service = svc.AnalystHistoryService()
    failed = asyncio.run(service.get("ZZZ"))
    assert failed.status == "unavailable" and failed.note_code == "fetch_failed"
    asyncio.run(service.get("ZZZ"))
    assert calls.count("ZZZ") == 2


def test_non_equity_is_sin_datos(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda s: {
            "records": [rec("A", date(2021, 1, 4), 150.0)],
            "closes": [],
            "splits": [],
            "currency": "USD",
            "quote_type": "ETF",
            "first_trade_date": None,
        },
    )
    out = asyncio.run(svc.AnalystHistoryService().get("SPY"))
    assert out.status == "empty" and out.note_code == "not_equity" and out.horizons == []


def test_mocked_yahoo_frames_are_parsed(monkeypatch) -> None:
    import pandas as pd
    import yfinance as yf

    ud = pd.DataFrame(
        {"Firm": ["Acme"], "Action": ["up"], "currentPriceTarget": [500.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2022-05-01 12:00")], name="GradeDate"),
    )
    hist = pd.DataFrame(
        {"Close": [100.0, 11.0], "Stock Splits": [0.0, 10.0]},
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2022-05-02", tz="America/New_York"),
                pd.Timestamp("2022-06-10", tz="America/New_York"),
            ]
        ),
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.upgrades_downgrades = ud

        def history(self, **kwargs):
            assert kwargs["auto_adjust"] is False
            return hist

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    records = svc._fetch_history_records("ACME")
    prices = svc._fetch_prices("ACME")
    assert records[0]["firm"] == "Acme" and records[0]["grade_action"] == "up"
    assert prices["closes"] == [(date(2022, 5, 2), 100.0), (date(2022, 6, 10), 11.0)]
    assert prices["splits"] == [(date(2022, 6, 10), 10.0)]
    targets = svc.normalize_targets(records, prices["splits"])
    assert targets[0]["target"] == pytest.approx(50.0)
