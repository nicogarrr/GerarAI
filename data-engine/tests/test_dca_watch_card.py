"""Tarjeta DCA de la watchlist: mismo motor por semana/mes/trimestre/año, racha, riesgo y cambio."""

from __future__ import annotations

import math
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    ZONES,
    DailyBar,
    evaluate_series,
    monthly_closes,
    period_closes,
    period_key,
)
from app.services.dca_watch_card import build_watch_card


def _bars(monthly_path: list[float], start: date = date(2010, 1, 4)) -> list[DailyBar]:
    """Barras diarias de lunes a viernes interpolando un cierre mensual objetivo."""
    bars = []
    day = start
    prev = monthly_path[0]
    for target in monthly_path:
        month = day.month
        days = []
        while day.month == month:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        for k, d in enumerate(days, start=1):
            close = prev * (target / prev) ** (k / len(days))
            # Pequeña ondulación diaria para que la vol no sea cero.
            close *= 1.0 + 0.01 * math.sin(d.toordinal())
            bars.append(DailyBar(day=d, close=close, low=close * 0.99))
        prev = target
    return bars


RISE_THEN_CRASH = [100 * 1.02**i for i in range(60)] + [100 * 1.02**59 * (0.93**k) for k in range(1, 9)]


def test_period_keys_and_grouping():
    assert period_key(date(2026, 11, 7), "week") == "2026-W45"
    assert period_key(date(2026, 11, 7), "quarter") == "2026-Q4"
    assert period_key(date(2026, 11, 7), "year") == "2026"
    assert period_key(date(2026, 11, 7)) == "2026-11"
    bars = _bars(RISE_THEN_CRASH)
    assert period_closes(bars, "month") == monthly_closes(bars)
    quarters = period_closes(bars, "quarter")
    assert [q[0] for q in quarters[:3]] == ["2010-Q1", "2010-Q2", "2010-Q3"]
    q1_days = [b for b in bars if b.day < date(2010, 4, 1)]
    assert quarters[0][2] == pytest.approx(q1_days[-1].close)
    assert quarters[0][3] == pytest.approx(min(b.low for b in q1_days))
    with pytest.raises(ValueError):
        period_key(date(2026, 1, 1), "decade")


def test_monthly_signal_is_unchanged_by_the_new_period_argument():
    bars = _bars(RISE_THEN_CRASH)
    today = bars[-1].day
    assert evaluate_series(bars, today=today, period="month") == evaluate_series(bars, today=today)


def test_weekly_vol_is_annualised_with_52_periods():
    bars = _bars(RISE_THEN_CRASH)
    weekly = evaluate_series(bars, today=bars[-1].day, period="week")
    last = weekly[-1]
    closes = [c for _k, _d, c, _l in period_closes(bars, "week")]
    i = len(closes) - 1
    rets = [math.log(closes[j] / closes[j - 1]) for j in range(max(1, i - DEFAULT_PARAMS.vol_lookback_months), i)]
    mean = sum(rets) / len(rets)
    expected = math.sqrt(sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)) * math.sqrt(52)
    assert last.metrics["vol"] == pytest.approx(expected, abs=1e-6)


def test_card_levels_streak_last_change_and_why():
    bars = _bars(RISE_THEN_CRASH)
    card = build_watch_card(bars, today=bars[-1].day + timedelta(days=40))
    assert card["available"] is True
    monthly = evaluate_series(bars, today=bars[-1].day + timedelta(days=40))
    assert card["current"]["level"] == monthly[-1].level >= 3
    assert card["current"]["color"] == ZONES[monthly[-1].level]["color"]
    streak = 0
    for v in reversed(monthly):
        if v.level != monthly[-1].level:
            break
        streak += 1
    assert card["current"]["months_in_zone"] == streak
    change = card["last_change"]
    previous = monthly[-1 - streak]
    assert change["from"]["level"] == previous.level != monthly[-1].level
    assert change["close"] == pytest.approx(previous.close)
    assert change["change"] == pytest.approx(monthly[-1].close / previous.close - 1)
    assert change["change"] < 0
    keys = [tf["key"] for tf in card["timeframes"]]
    assert keys == ["week", "month", "quarter", "year"]
    month_tf = card["timeframes"][1]
    assert month_tf["zone"]["level"] == monthly[-1].level
    # 68 meses: el año no tiene 12 periodos todavía y lo dice.
    year_tf = card["timeframes"][3]
    assert year_tf["available"] is False and "12 periodos" in year_tf["reason"]
    assert card["timeframes"][2]["available"] is True
    why = card["why"]
    assert why["drawdown"] == monthly[-1].metrics["drawdown"]
    assert why["dd_thresholds"] == list(DEFAULT_PARAMS.dd_thresholds)
    assert set(why["level_prices"]) == {"2x", "3x", "4x"}


def test_zone_colours_are_gerarai_s_own_unchanged():
    assert ZONES[4]["color"] == "#B400FF"
    assert ZONES[3]["color"] == "#68F60F"
    assert ZONES[2]["color"] == "#00AA78"


def test_risk_tag_from_volatility_pre_revenue_and_history():
    calm = _bars([100 * 1.005**i for i in range(60)])
    card = build_watch_card(calm, today=calm[-1].day)
    assert card["risk"]["key"] == "low"
    assert build_watch_card(calm, today=calm[-1].day, pre_revenue=True)["risk"]["key"] == "high"
    wild = _bars([100 * (1.6 if i % 2 else 0.6) ** (i % 2) * (1.0 + 0.3 * math.sin(i)) for i in range(60)])
    assert build_watch_card(wild, today=wild[-1].day)["risk"]["key"] == "high"
    young = _bars([100 * 1.005**i for i in range(20)])
    risk = build_watch_card(young, today=young[-1].day)["risk"]
    assert risk["key"] == "medium"
    assert any(r["key"] == "short_history" for r in risk["reasons"])
    stale = build_watch_card(calm, today=calm[-1].day, stale=True)["risk"]
    assert any(r["key"] == "stale" for r in stale["reasons"])


def test_too_short_history_says_so():
    short = _bars([100.0] * 5)
    card = build_watch_card(short, today=short[-1].day)
    assert card["available"] is False
    # 5 meses: la semana ya tiene 12 periodos; mes, trimestre y año no.
    assert [tf["available"] for tf in card["timeframes"]] == [True, False, False, False]


def test_route_uses_the_daily_signal_series(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.routes import watchlist as route
    from app.models.entities import Base
    from app.services import dca_signal_service as svc
    from app.services.dca_signal_service import PriceRow

    bars = _bars(RISE_THEN_CRASH, start=date(2020, 1, 6))
    rows = [PriceRow(day=b.day, close=b.close, adj_close=b.close) for b in bars]
    monkeypatch.setattr(svc, "fetch_yahoo_history_cached", lambda symbol: SimpleNamespace(rows=rows, currency="USD"))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        out = route.dca_watch_card("intc", db)
    assert out["symbol"] == "INTC" and out["available"] is True
    assert out["currency"] == "USD"
    assert [tf["short"] for tf in out["timeframes"]] == ["S", "M", "T", "A"]
