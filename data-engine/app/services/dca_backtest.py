"""Backtest DCA plano vs DCA por niveles (Formula Nico v1) para un ticker.

Puro (sin DB ni red) y sin look-ahead, con las mismas convenciones que el
backtest de investigacion con el que se calibro la formula:

* El veredicto del mes ``t`` usa solo cierres hasta el ultimo dia de ``t``
  (``evaluate_series``); el mes en formacion no se usa.
* La compra del mes ``t`` se ejecuta al PRIMER cierre diario de ``t+1``.
* La cartera se valora al ultimo cierre del mes de la ultima compra.

Tres planes con el mismo calendario de compras:

* ``plain``: aporta ``base`` cada mes.
* ``levels``: aporta ``base x multiplicador`` (1X..4X; los recortes son
  informativos y cuentan como 1X, no se vende nada). Usa MAS dinero.
* ``fixed_budget``: entra ``base`` cada mes; en 1X invierte la mitad y guarda
  el resto en caja para gastarlo (hasta ``nivel x base/2``) en meses 2X-4X.
  Mismo dinero que ``plain``: es la comparacion honesta de presupuesto cerrado.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    ZONES,
    DailyBar,
    DcaParams,
    evaluate_series,
    hit_rates,
    monthly_closes,
)

FIXED_BUDGET_UNIT = 0.5  # fraccion de la aportacion base que compra un mes 1X


def _month_index(period: str) -> int:
    return int(period[:4]) * 12 + int(period[5:7]) - 1


def _period_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def irr_monthly(flows: list[float]) -> float | None:
    """TIR anualizada de flujos mensuales consecutivos (negativo = aportacion)."""
    if len(flows) < 2 or not any(f < 0 for f in flows) or not any(f > 0 for f in flows):
        return None

    def npv(rate: float) -> float:
        return sum(f / (1.0 + rate) ** i for i, f in enumerate(flows))

    lo, hi = -0.5, 0.5
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (1.0 + (lo + hi) / 2) ** 12 - 1.0


def _multiplier(level: int) -> float:
    return float(level) if level >= 1 else 1.0


def _plan_summary(
    name: str,
    label: str,
    buys: list[tuple[int, float, float]],
    month_values: list[tuple[int, float]],
    final_price: float,
    final_offset: int,
    cash: float = 0.0,
) -> dict:
    """``buys`` = (offset de mes, importe, precio). ``month_values`` = (offset, cierre de mes)."""
    invested = sum(amount for _, amount, _ in buys)
    shares = sum(amount / price for _, amount, price in buys)
    final_value = shares * final_price + cash
    # Compras al primer cierre de cada mes y valoracion al cierre del ultimo mes:
    # un periodo mensual entre la ultima compra y la valoracion (como el backtest
    # de investigacion).
    flows = [0.0] * (final_offset + 2)
    for offset, amount, _ in buys:
        flows[offset] -= amount
    if name == "fixed_budget":
        # Presupuesto cerrado: los flujos son las ENTRADAS de dinero (base cada mes).
        flows = [0.0] * (final_offset + 2)
        for offset, _, _ in buys:
            flows[offset] -= 1.0
        scale = invested + cash
        total_in = sum(-f for f in flows)
        flows = [f * scale / total_in for f in flows] if total_in else flows
    flows[final_offset + 1] += final_value
    # Curva de la cartera a cierre de mes: TWR (sin el efecto de las aportaciones)
    # y peor perdida latente frente a lo aportado hasta ese mes.
    by_offset: dict[int, list[tuple[float, float]]] = {}
    for offset, amount, price in buys:
        by_offset.setdefault(offset, []).append((amount, price))
    held = 0.0
    put_in = 0.0
    prev_value = None
    index = 1.0
    peak = 1.0
    max_dd = 0.0
    worst = 0.0
    for offset, close in month_values:
        if prev_value is not None and prev_value > 0:
            index *= (held * close) / prev_value
            peak = max(peak, index)
            max_dd = min(max_dd, index / peak - 1.0)
        for amount, price in by_offset.get(offset, []):
            held += amount / price
            put_in += amount
        value = held * close
        if put_in > 0:
            worst = min(worst, value / put_in - 1.0)
        prev_value = value if value > 0 else None
    return {
        "key": name,
        "label": label,
        "invested": round(invested + (cash if name == "fixed_budget" else 0.0), 6),
        "deployed": round(invested, 6),
        "cash_left": round(cash, 6),
        "shares": round(shares, 8),
        "avg_cost": round(invested / shares, 6) if shares else None,
        "final_value": round(final_value, 6),
        "multiple": round(final_value / (invested + cash), 6) if (invested + cash) else None,
        "irr": None if (r := irr_monthly(flows)) is None else round(r, 6),
        "max_drawdown": round(max_dd, 6),
        "worst_unrealized": round(worst, 6),
        "buys": len(buys),
    }


def backtest_dca(
    bars: Iterable[DailyBar],
    *,
    params: DcaParams = DEFAULT_PARAMS,
    start: str | None = None,
    end: str | None = None,
    base_amount: float = 100.0,
    today: date | None = None,
) -> dict:
    """DCA plano vs DCA por niveles entre ``start`` y ``end`` (YYYY-MM, incluidos)."""
    if base_amount <= 0 or not math.isfinite(base_amount):
        raise ValueError("base_amount debe ser > 0")
    bars = sorted(bars, key=lambda b: b.day)
    verdicts = [v for v in evaluate_series(bars, params=params, today=today) if v.status == "confirmed"]
    first_close: dict[str, tuple[date, float]] = {}
    for bar in bars:
        if bar.close and bar.close > 0 and math.isfinite(bar.close):
            first_close.setdefault(_period_of(bar.day), (bar.day, float(bar.close)))
    monthly = monthly_closes(bars)
    month_close = {key: close for key, _day, close, _low in monthly}
    month_close_day = {key: day for key, day, _close, _low in monthly}

    def _next(period: str) -> str:
        n = _month_index(period) + 1
        return f"{n // 12:04d}-{n % 12 + 1:02d}"

    plan = []  # (periodo senal, nivel, fecha compra, precio compra)
    for v in verdicts:
        if (start and v.period < start) or (end and v.period > end):
            continue
        nxt = first_close.get(_next(v.period))
        if nxt is None:
            continue  # sin cierre del mes siguiente todavia: no hay compra
        plan.append((v.period, v.level, nxt[0], nxt[1]))
    if len(plan) < 2:
        return {
            "available": False,
            "reason": "Historia insuficiente en ese rango: hacen falta al menos 2 meses con veredicto confirmado y compra.",
            "params_version": params.version,
        }
    origin = _month_index(_next(plan[0][0]))
    last_buy_period = _next(plan[-1][0])
    final_offset = _month_index(last_buy_period) - origin
    final_price = month_close[last_buy_period]
    month_values = [
        (_month_index(p) - origin, c)
        for p, c in sorted(month_close.items())
        if 0 <= _month_index(p) - origin <= final_offset
    ]
    plain, levels, fixed = [], [], []
    cash = 0.0
    counts: dict[int, int] = {}
    for period, level, _day, price in plan:
        offset = _month_index(_next(period)) - origin
        mult = _multiplier(level)
        counts[level] = counts.get(level, 0) + 1
        plain.append((offset, base_amount, price))
        levels.append((offset, base_amount * mult, price))
        cash += base_amount
        spend = min(cash, mult * base_amount * FIXED_BUDGET_UNIT)
        if spend > 0:
            fixed.append((offset, spend, price))
            cash -= spend
    plans = [
        _plan_summary("plain", "DCA plano", plain, month_values, final_price, final_offset),
        _plan_summary(
            "levels", "DCA por niveles (aporta extra)", levels, month_values, final_price, final_offset
        ),
        _plan_summary(
            "fixed_budget",
            "Niveles con presupuesto fijo",
            fixed,
            month_values,
            final_price,
            final_offset,
            cash=cash,
        ),
    ]
    base = plans[0]
    for p in plans[1:]:
        p["irr_vs_plain"] = (
            round(p["irr"] - base["irr"], 6) if p["irr"] is not None and base["irr"] is not None else None
        )
        p["value_vs_plain"] = (
            round(p["final_value"] / base["final_value"] - 1.0, 6) if base["final_value"] else None
        )
    plans[1]["shares_per_money_vs_plain"] = (
        round((plans[1]["shares"] / plans[1]["deployed"]) / (base["shares"] / base["deployed"]) - 1.0, 6)
        if base["shares"] and plans[1]["deployed"]
        else None
    )
    level_rows = [
        {"level": lvl, "label": ZONES[lvl]["label"], "color": ZONES[lvl]["color"], "months": counts[lvl]}
        for lvl in sorted(counts, reverse=True)
    ]
    hits = hit_rates(bars, params=params, today=today, start=plan[0][0], end=plan[-1][0])
    return {
        "available": True,
        "params_version": params.version,
        "first_signal": plan[0][0],
        "last_signal": plan[-1][0],
        "first_buy": plan[0][2].isoformat(),
        "last_buy": plan[-1][2].isoformat(),
        "valued_at_period": last_buy_period,
        # Fecha real del cierre usado. Si el mes aun no ha terminado no es «el
        # cierre de 2026-10» sino el ultimo cierre disponible: se dice.
        "valued_at_date": month_close_day[last_buy_period].isoformat(),
        "valued_month_complete": _month_index(last_buy_period)
        < _month_index(_period_of(today or date.today())),
        "final_price": round(final_price, 6),
        "months": len(plan),
        "base_amount": base_amount,
        "plans": plans,
        "levels": level_rows,
        "hit_rates": hits,
    }
